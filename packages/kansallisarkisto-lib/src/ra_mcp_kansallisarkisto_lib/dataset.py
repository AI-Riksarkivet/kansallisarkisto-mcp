"""Shared LanceDB spine for the Sisältöhaku corpora.

One place for the :class:`SearchResult` envelope, cached connections, full-text
index construction, SQL predicate builders and the paginated search itself — so
`df`, `voudintilit` and `tuomiokirjat` share a single implementation instead of
each growing its own copy (and its own copy of the same bugs).

Ported from ra-mcp's ``ra_mcp_dataset_lib``, with its OpenTelemetry layer left
out: this server, like ape-mcp, has no telemetry stack.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from lancedb.index import FTS, Bitmap, BTree
from lancedb.query import BooleanQuery, FullTextOperator, FullTextQuery, MatchQuery, Occur
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel

from .telemetry import get_meter, get_tracer, record_span_exception

if TYPE_CHECKING:
    import lancedb

logger = logging.getLogger(__name__)

# lancedb exposes no count API on an FTS query, so total_hits is a true match
# count only up to this bound — far above any realistic page, and honest in a way
# a len-of-the-current-window total (which can never exceed limit + offset) is not.
# A search that reaches the bound sets SearchResult.total_is_capped, so the total
# is reported as a floor ("10000+") rather than passed off as exact.
MAX_TOTAL_COUNT = 10_000

# The column the full-text index is built over. It concatenates columns the row
# already carries, so returning it doubles the payload of every result for no
# information — searches project it away by default.
FTS_COLUMN = "searchable_text"

# Edit distance allowed per term, and it is off by default because the engine
# makes fuzzy matching and stemming mutually exclusive.
#
# Both address real recall problems in this corpus and neither subsumes the
# other. Stemming handles inflection: "konungen" finds all 279 charters that
# stem to "konung". Fuzzy handles orthography, which is the bigger problem here
# — spelling was not standardised, so "bref" matches 257 charters while "breff"
# matches 1,918 and only 71 overlap; one edit takes "bref" to 2,212 charters
# with 96.9% of them still containing a real variant.
#
# But a fuzzy term skips the analysis pipeline, so it is matched raw against
# stemmed index terms: "konungen" collapses from 279 hits to 6, and a word that
# only matched via its stem disappears outright. Trading a reliable mechanism
# for an unreliable one is the wrong default, so exact-plus-stemming wins and
# fuzzy is an explicit widening — best used on a base form rather than an
# inflected one.
DEFAULT_FUZZINESS = 0


class SearchInputError(ValueError):
    """A search argument the caller can correct, as opposed to a server fault.

    Subclasses ``ValueError`` so existing callers that catch one keep working.
    It exists so the MCP layer can tell *this* library's validation messages —
    which are written for the caller and safe to return — from an arbitrary
    ``ValueError``, which is not: lancedb raises ``ValueError`` too, and its
    messages quote on-disk dataset paths and internal query structure. Catching
    the base class would hand those straight to a public HTTP client, which is
    exactly what ``formatter.format_error`` exists to prevent.
    """


_tracer = get_tracer("kansallisarkisto.lancedb")
_meter = get_meter("kansallisarkisto.lancedb")
# RED metrics on the busiest surface: every corpus search passes through here.
# Attempts are counted whether they succeed or fail, so an error-rate panel and a
# latency percentile both work — a success-only counter gives neither.
_query_counter = _meter.create_counter("kansallisarkisto.lancedb.queries", unit="{query}", description="LanceDB full-text search queries attempted")
_error_counter = _meter.create_counter("kansallisarkisto.lancedb.errors", unit="{error}", description="LanceDB full-text search failures")
_query_duration = _meter.create_histogram("kansallisarkisto.lancedb.query.duration", unit="s", description="LanceDB full-text search duration")
# Behavioural signal rather than a health one: the zero bucket is "searches that
# matched nothing" — what people looked for that this corpus cannot answer. The
# terms themselves stay on the span (db.query.text), not on the metric.
_results_histogram = _meter.create_histogram("kansallisarkisto.lancedb.results", unit="{hit}", description="Total matches per LanceDB search")

_connections: dict[str, lancedb.DBConnection] = {}
_connections_lock = threading.Lock()


class SearchResult(BaseModel):
    """One page of a corpus full-text search plus the total match count."""

    records: list[dict[str, Any]]
    total_hits: int
    keyword: str
    offset: int
    limit: int
    # True when the match count hit MAX_TOTAL_COUNT, i.e. total_hits is a floor
    # rather than the real total. Never true for df (6,876 rows); routine for
    # tuomiokirjat (7.8M), which is why it is on the shared envelope.
    total_is_capped: bool = False
    # Things the caller should know about how the search was run — a prefix that
    # was truncated to its most frequent forms, a filter that leaves out part of
    # the corpus. Rendered after the results, never instead of them.
    notes: list[str] = []


def get_lancedb(uri: str) -> lancedb.DBConnection:
    """Return a process-cached LanceDB connection for ``uri`` (thread-safe lazy init).

    LanceDB connections are ``Send + Sync`` and have no ``close()``; caching one
    per URI for the process lifetime is the intended usage.
    """
    conn = _connections.get(uri)
    if conn is None:
        with _connections_lock:
            conn = _connections.get(uri)
            if conn is None:
                import lancedb

                conn = lancedb.connect(uri)
                _connections[uri] = conn
    return conn


def table_names(db: lancedb.DBConnection) -> list[str]:
    """Return the table names in ``db``, sorted.

    Wraps ``list_tables()``, which returns a paginated response object rather
    than the plain list its deprecated predecessor ``table_names()`` gave — so
    callers ask a question ("what is in this database?") instead of encoding
    lancedb's response shape.
    """
    return sorted(db.list_tables().tables)


def build_fts_index(
    db: lancedb.DBConnection,
    table_name: str,
    column: str = FTS_COLUMN,
    *,
    language: str = "Swedish",
) -> lancedb.table.Table:
    """Build (or replace) a full-text index on ``table_name.column``.

    The text of all three corpora is early-modern Swedish, not Finnish — Finland
    was part of the Swedish realm until 1809 and these records were kept in the
    administrative language of the day. So ``language="Swedish"`` with stemming is
    the right default: an inflected query matches ("konungen" finds "konung",
    "konungs"). ``df`` is the one corpus where that is only a 44% plurality choice
    (2,870 of its 6,876 records are Latin or German); Swedish stemming still wins
    there, but callers can override.

    ``stem`` and ``remove_stop_words`` are passed explicitly rather than left to
    the lancedb default, which has flipped between releases — and with ``stem``
    off, ``language`` silently does nothing at all. Pinning them keeps the index
    behaviour tied to this code rather than to the version pin.

    ``ascii_folding`` matters for this material specifically: place names appear
    both accented and unaccented across four centuries of orthography, so "Abo"
    must find "Åbo". ``max_token_length`` is raised from the lancedb default of 40
    so long Swedish compounds are not dropped and made unsearchable.

    Returns the freshly-opened table handle that carries the new index. A handle
    opened before the index (e.g. the one ``create_table`` returned during ingest)
    does not see it and would fail a full-text search, so ingest should return
    *this* handle rather than its pre-index one.
    """
    table = db.open_table(table_name)
    table.create_index(
        column,
        config=FTS(
            language=language,
            stem=True,
            # Stop words are KEPT, which is not the usual default and is a
            # consequence of the corpus being multilingual. Swedish stop words are
            # Latin content words: with removal on, "de" (a token in 1,735
            # documents), "den" (846) and "om" (1,133) returned nothing at all,
            # because a Swedish analyser had discarded them at index time. They are
            # function words in the plurality language and meaningful in the rest,
            # so the recall loss is not worth the smaller index.
            remove_stop_words=False,
            # Positions cost index size and buy phrase queries. Without them a
            # quoted query does not merely miss, it raises — which the MCP layer
            # can only report as an internal error for what is a perfectly
            # reasonable search.
            with_position=True,
            ascii_folding=True,
            max_token_length=64,
        ),
        replace=True,
    )
    return table


def build_scalar_indexes(
    db: lancedb.DBConnection,
    table_name: str,
    *,
    btree: Sequence[str] = (),
    bitmap: Sequence[str] = (),
) -> lancedb.table.Table:
    """Build scalar indexes on the columns a corpus filters on, so ``.where()``
    predicate push-down is an index lookup instead of a full column scan.

    - ``btree``: ordered columns used in equality or range predicates — ids and
      years (``df_number = X``, ``year_from >= 1400``).
    - ``bitmap``: low-cardinality categoricals used in equality predicates
      (``language = 'latina'``), where a per-value bitmap beats a btree.

    Substring filters (:func:`text_contains` → ``lower(col) LIKE '%v%'``) are
    deliberately left unindexed: a leading-wildcard ``LIKE`` cannot use a
    BTree/Bitmap.

    Like :func:`build_fts_index`, call this once during ingest and return its
    handle. Building an index mutates the on-disk dataset, so it belongs in the
    ingest path — never against already-published live data.
    """
    table = db.open_table(table_name)
    for column in btree:
        table.create_index(column, config=BTree(), replace=True)
    for column in bitmap:
        table.create_index(column, config=Bitmap(), replace=True)
    return table


# --- prefix search --------------------------------------------------------------
# The engine has no wildcard: "lepros*" matches nothing. And its stemmer is
# Swedish, so the Latin and German that make up 42% of df are never stemmed —
# "leprosorum", "leprosi" and "leprosis" are three unrelated tokens. Fuzzy
# matching does not bridge them either: it is whole-word edit distance, and
# "lepros" is four edits from "leprosorum". That is how the one charter about
# the leper house at Reval (DF 173) stayed invisible to every obvious query.
#
# So a trailing * is expanded here, against the table's own vocabulary, into an
# OR of every form that begins that way; "a|b" in a term does the same for
# spellings the caller lists. The vocabulary is built on first use from the
# indexed text and cached for the process. It is bounded by row count because a
# corpus of millions of OCR pages cannot hold one in memory — voudintilit alone
# has 1.15M distinct forms and takes 13 s to tokenise, df 140K forms in 0.8 s.

PREFIX_MIN_CHARS = 3
# An expansion is an OR of this many match clauses; 500 ran in 90 ms on df, so
# the cap is about keeping "kon*" (347 forms) meaningful, not about speed. A
# search that hits it says so in a note.
MAX_PREFIX_EXPANSIONS = 300
MAX_VOCABULARY_ROWS = 50_000

_PREFIX_TERM = re.compile(rf"^(\w{{{PREFIX_MIN_CHARS},}})\*$")
_TOKEN = re.compile(r"\w+")
_vocabularies: dict[tuple[str, str, str], dict[str, int]] = {}
_vocabularies_lock = threading.Lock()


def fold_token(text: str) -> str:
    """Lower-case and strip accents the way the index's ASCII folding does, so a
    prefix typed as ``Åbo`` meets the vocabulary's ``abo`` and ``ræffl`` its
    ``raeffl``."""
    text = text.lower().replace("æ", "ae").replace("ø", "o").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def vocabulary(db: lancedb.DBConnection, table_name: str, fts_column: str = FTS_COLUMN) -> dict[str, int]:
    """The distinct folded word forms of ``table_name.fts_column`` and how many
    rows each occurs in, built once per process (thread-safe lazy init).

    Raises:
        SearchInputError: when the table is too large to hold a vocabulary; the
            message tells the caller what to do instead.
    """
    key = (str(db.uri), table_name, fts_column)
    vocab = _vocabularies.get(key)
    if vocab is None:
        with _vocabularies_lock:
            vocab = _vocabularies.get(key)
            if vocab is None:
                vocab = _build_vocabulary(db, table_name, fts_column)
                _vocabularies[key] = vocab
    return vocab


def _build_vocabulary(db: lancedb.DBConnection, table_name: str, fts_column: str) -> dict[str, int]:
    table = db.open_table(table_name)
    rows = table.count_rows()
    if rows > MAX_VOCABULARY_ROWS:
        raise SearchInputError(
            f"prefix search (a trailing *) is not available on this corpus: {rows:,} rows is too many to hold a vocabulary. Search whole words instead, listing spellings as alternatives ('bref|breff') or with fuzzy=1."
        )
    counts: dict[str, int] = {}
    if rows == 0:
        return counts
    with _tracer.start_as_current_span(f"vocabulary {table_name}", kind=SpanKind.CLIENT, attributes={"db.system": "lancedb", "db.collection.name": table_name, "db.operation.name": "scan"}) as span:
        for row in table.search().select([fts_column]).limit(rows).to_list():
            for token in set(_TOKEN.findall(fold_token(row[fts_column] or ""))):
                counts[token] = counts.get(token, 0) + 1
        span.set_attribute("db.response.returned_rows", rows)
        span.set_attribute("kansallisarkisto.vocabulary.size", len(counts))
    return counts


def expand_prefix(vocab: dict[str, int], prefix: str) -> tuple[list[str], int]:
    """The forms in ``vocab`` beginning with ``prefix``, most frequent first and
    capped at :data:`MAX_PREFIX_EXPANSIONS`, plus how many there were in all."""
    needle = fold_token(prefix)
    forms = sorted(((count, form) for form, count in vocab.items() if form.startswith(needle)), key=lambda item: (-item[0], item[1]))
    return [form for _, form in forms[:MAX_PREFIX_EXPANSIONS]], len(forms)


def _needs_expansion(keyword: str) -> bool:
    return "*" in keyword or "|" in keyword


def _expanded_query(
    db: lancedb.DBConnection,
    table_name: str,
    keyword: str,
    *,
    fts_column: str,
    match_all: bool,
    fuzzy: int,
    notes: list[str],
) -> FullTextQuery | None:
    """Build the boolean query for a keyword that uses ``*`` or ``|``.

    Each whitespace-separated term becomes one clause — MUST under ``match_all``,
    SHOULD otherwise — and within a term, ``|``-separated alternatives and the
    expansions of a ``prefix*`` are ORed. Plain alternatives keep the caller's
    ``fuzzy``; expanded forms are exact, since they came from the index itself.

    Returns ``None`` when nothing could match: a required prefix that begins no
    word in the corpus, or a keyword that was only punctuation.
    """
    occur = Occur.MUST if match_all else Occur.SHOULD
    clauses: list[tuple[Occur, FullTextQuery]] = []
    for term in keyword.split():
        # A bare "*" or "|" is punctuation, not a term; it must not raise, because
        # the keyword comes from a model and will eventually contain either alone.
        alternatives = [alt for alt in term.split("|") if alt and alt != "*"]
        if not alternatives:
            continue
        queries: list[FullTextQuery] = []
        for alt in alternatives:
            if alt.endswith("*"):
                matched = _PREFIX_TERM.match(alt)
                if matched is None:
                    raise SearchInputError(f"'{alt}': a prefix needs at least {PREFIX_MIN_CHARS} characters before the *")
                stem = matched.group(1)
                forms, available = expand_prefix(vocabulary(db, table_name, fts_column), stem)
                if not forms:
                    notes.append(f"No word in this corpus begins with '{stem}'.")
                elif available > len(forms):
                    notes.append(f"'{alt}' begins {available:,} distinct forms in this corpus; only the {len(forms)} most frequent were searched. Lengthen the prefix to narrow it.")
                queries.extend(MatchQuery(form, column=fts_column) for form in forms)
            elif "*" in alt:
                raise SearchInputError(f"'{alt}': * is only supported at the end of a term, as in 'lepros*'")
            else:
                queries.append(MatchQuery(alt, column=fts_column, fuzziness=fuzzy))
        if not queries:
            if match_all:
                return None
            continue
        clause = queries[0] if len(queries) == 1 else BooleanQuery([(Occur.SHOULD, query) for query in queries])
        clauses.append((occur, clause))
    return BooleanQuery(clauses) if clauses else None


def lancedb_fts_search(
    db: lancedb.DBConnection,
    table_name: str,
    keyword: str,
    *,
    limit: int,
    offset: int = 0,
    where: str | None = None,
    columns: Sequence[str] | None = None,
    match_all: bool = True,
    fuzzy: int = DEFAULT_FUZZINESS,
) -> SearchResult:
    """Full-text search returning one correctly-paginated page and a true total.

    Filters are pushed into LanceDB via ``where`` (a SQL predicate), so both the
    total and the page are computed over the already-filtered result set.

    The ranked result set is fetched once (up to :data:`MAX_TOTAL_COUNT`) and the
    page is sliced from it. One ranked query is used deliberately rather than
    native ``.offset()`` across separate queries: BM25 score ties reorder results
    between queries, so per-query offsets drop and duplicate rows. Slicing a
    single ranked set gives both a real ``total_hits`` and stable pagination.

    Fetching the whole ranked set is also what makes the projection matter: every
    search materialises up to ``MAX_TOTAL_COUNT`` rows to count them, and all but
    ``limit`` of those are then discarded. ``columns`` defaults to every column
    except :data:`FTS_COLUMN`, which halves that payload (measured on df: 6.1 MB
    to 3.3 MB for one 1,451-hit query) because the FTS column only repeats text
    the row already carries. ``_score`` is requested explicitly: lancedb still
    auto-projects it when a ``select`` omits it, but warns that it will stop.

    ``match_all`` decides what a multi-word keyword means. The engine's own
    default is OR, which makes ``total_hits`` badly misleading: "konung
    Stockholm" matches 944 charters, nearly all of them on one word alone, and a
    caller reasonably reads 944 as "documents about the king in Stockholm". BM25
    still floats the good ones to the top — 19 of the first 20 contained both
    terms — but the total is a claim about the whole result set, not the page.
    Requiring every term gives 77, which is the number that was actually meant.
    Pass ``match_all=False`` to widen when a term may be spelled differently.

    ``fuzzy`` is the edit distance allowed per term, defaulting to
    :data:`DEFAULT_FUZZINESS`; see that constant for why it is 0. Raise it to
    reach spelling variants, at the cost of stemming.

    Fuzziness cannot be combined with a quoted phrase: the phrase goes to the
    query parser, which takes no fuzziness argument. Rather than drop the
    argument silently, that combination raises.

    Raises:
        SearchInputError: if ``keyword`` is blank, ``offset`` is negative, ``limit`` < 1,
            or ``fuzzy`` is combined with a quoted phrase. A ``ValueError`` subclass, and
            the only error type whose message is safe to show a caller.
    """
    if not keyword or not keyword.strip():
        raise SearchInputError("keyword must be non-empty")
    # Guard paging centrally so every tool inherits it: without this a negative
    # offset or limit < 1 slices matches[] into an empty/partial window while
    # total_hits stays nonzero, so the formatter misreports "no results" or emits
    # a broken "offset=-N" pagination footer.
    if offset < 0:
        raise SearchInputError(f"offset must be >= 0 (got {offset})")
    if limit < 1:
        raise SearchInputError(f"limit must be >= 1 (got {limit})")

    table = db.open_table(table_name)
    notes: list[str] = []
    # A quoted keyword goes to the query parser, which is what understands phrase
    # syntax; MatchQuery would match the quote characters themselves and silently
    # turn '"de ecclesia"' from 8 hits into 496. Everything else goes through
    # MatchQuery so that match_all can be honoured — the parser has no AND.
    if '"' in keyword:
        # The parser is what understands phrase syntax, and it has no fuzziness
        # argument. Silently dropping the caller's fuzzy= is the same failure the
        # tool descriptions were just cleaned of: a parameter that is offered and
        # then quietly discarded.
        if fuzzy:
            raise SearchInputError(f"fuzzy={fuzzy} cannot be combined with a quoted phrase; drop the quotes to search the words fuzzily, or use fuzzy=0 for the exact phrase")
        request: Any = keyword
    elif _needs_expansion(keyword):
        request = _expanded_query(db, table_name, keyword, fts_column=FTS_COLUMN, match_all=match_all, fuzzy=fuzzy, notes=notes)
        if request is None:
            # Nothing in the corpus can satisfy this — an ordinary empty answer,
            # and one worth counting as such.
            _results_histogram.record(0, {"db.system": "lancedb", "db.collection.name": table_name})
            return SearchResult(records=[], total_hits=0, keyword=keyword, offset=offset, limit=limit, notes=notes)
    else:
        operator = FullTextOperator.AND if match_all else FullTextOperator.OR
        request = MatchQuery(keyword, column=FTS_COLUMN, operator=operator, fuzziness=fuzzy)
    query: Any = table.search(request, query_type="fts")
    if columns is None:
        columns = [name for name in table.schema.names if name != FTS_COLUMN]
    query = query.select([*columns, "_score"])
    if where:
        query = query.where(where)
    # The tables are built once (create_table + create_index) and never appended
    # to, so there is no unindexed data — fast_search skips the redundant flat
    # search of unindexed rows with no loss of results.
    query = query.fast_search()

    # The span covers the query itself, not the predicate building above: this is
    # the part that does I/O and the part that can be slow.
    attrs = {"db.system": "lancedb", "db.collection.name": table_name}
    span_attrs: dict[str, Any] = {**attrs, "db.operation.name": "fts_search", "db.query.text": keyword, "db.query.match_all": match_all, "db.query.fuzzy": fuzzy}
    if where:
        span_attrs["db.query.filter"] = where
    with _tracer.start_as_current_span(f"search {table_name}", kind=SpanKind.CLIENT, attributes=span_attrs) as span:
        start = time.perf_counter()
        try:
            matches = query.limit(MAX_TOTAL_COUNT).to_list()
        except Exception as exc:
            span.set_status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}")
            record_span_exception(logger, exc)  # also sets error.type on the span
            _error_counter.add(1, {**attrs, "error.type": type(exc).__name__})
            raise
        finally:
            _query_duration.record(time.perf_counter() - start, attrs)
            _query_counter.add(1, attrs)

        total = len(matches)
        page = matches[offset : offset + limit]
        # total answers "how well did the corpus answer this", returned_rows "what
        # did the caller actually get" — they diverge on every paginated search.
        span.set_attribute("db.response.total_hits", total)
        span.set_attribute("db.response.returned_rows", len(page))
        span.set_attribute("db.response.total_is_capped", total >= MAX_TOTAL_COUNT)
        _results_histogram.record(total, attrs)

    return SearchResult(
        records=page,
        total_hits=total,
        keyword=keyword,
        offset=offset,
        limit=limit,
        total_is_capped=total >= MAX_TOTAL_COUNT,
        notes=notes,
    )


# --- SQL predicate builders ---------------------------------------------------
# Typed filters (a place, a year range, a language) become LanceDB ``.where()``
# predicates so filtering happens inside the query (pre-filter, before BM25)
# instead of in a Python loop over a truncated window. Building the SQL in one
# place keeps the quoting correct and un-duplicated.


def _sql_str(value: str) -> str:
    """Quote a Python string as a SQL string literal (single quotes doubled)."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _lit(value: str | int) -> str:
    """Render a scalar as a SQL literal — quoted for str, bare for int."""
    return str(value) if isinstance(value, int) else _sql_str(value)


# Column names are emitted bare, not double-quoted: LanceDB's filter parser reads
# a double-quoted "col" as a string LITERAL (SQLite-style), not an identifier, so
# quoting silently matches nothing. All columns here are simple snake_case
# identifiers, which the bare form handles correctly.


def text_contains(column: str, value: str) -> str:
    """Case-insensitive substring predicate: ``lower(col) LIKE '%value%'``.

    LIKE wildcards in ``value`` (``%`` ``_`` ``\\``) are escaped so a literal
    ``%`` in the filter matches a literal ``%``, not "anything".
    """
    needle = value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"lower({column}) LIKE {_sql_str(f'%{needle}%')} ESCAPE '\\'"


def equals(column: str, value: str | int) -> str:
    """Exact-match predicate: ``col = value``."""
    return f"{column} = {_lit(value)}"


def at_least(column: str, value: str | int) -> str:
    """Lower-bound predicate: ``col >= value`` (NULLs are excluded, as in SQL)."""
    return f"{column} >= {_lit(value)}"


def at_most(column: str, value: str | int) -> str:
    """Upper-bound predicate: ``col <= value`` (NULLs are excluded, as in SQL)."""
    return f"{column} <= {_lit(value)}"


def combine(*predicates: str | None) -> str | None:
    """AND-combine predicates, dropping ``None`` (an unset filter).

    Returns ``None`` when nothing is set, which :func:`lancedb_fts_search` treats
    as "no ``where`` clause".
    """
    parts = [p for p in predicates if p]
    if not parts:
        return None
    return " AND ".join(parts)


# --- shared handler / formatter scaffold --------------------------------------
# Every corpus tool wraps lancedb_fts_search in the same shape: guard an empty
# keyword, then render the page with an identical envelope. Only the label and
# the per-record rendering differ.


def require_keyword(keyword: str, example: str) -> str | None:
    """Validate a search keyword; return an error string when blank, else ``None``.

    Usage in a handler: ``if err := require_keyword(keyword, "'konung'"): return err``.
    ``example`` is a corpus-specific sample term shown in the message.
    """
    if not keyword or not keyword.strip():
        return f"Error: keyword must not be empty. Provide a search term, e.g. {example}."
    return None


def require_ordered_range[T: (int, str)](low: T | None, high: T | None, label: str) -> str | None:
    """Validate an optional ``[low, high]`` filter range; return an error string
    when it is inverted, else ``None``.

    Both bounds set with ``low > high`` builds an unsatisfiable predicate, which
    silently returns "no results" instead of flagging the swapped inputs.
    ``None`` for either bound means "unbounded on that side".
    """
    if low is not None and high is not None and low > high:
        return f"Error: {label} range is inverted — from/min ({low}) must be <= to/max ({high}). Swap the bounds."
    return None


def format_results(
    result: SearchResult,
    *,
    label: str,
    render_record: Callable[[dict[str, Any], list[str]], None],
) -> str:
    """Render a :class:`SearchResult` page as the standard plain-text block.

    Owns the envelope shared by every corpus formatter — the no-results and
    paginated-past-end messages, the header, and the "More results" footer.
    ``render_record(rec, lines)`` appends one record's lines and is the only
    genuinely per-corpus part.
    """
    # A capped total is a floor, not a count. Printing it bare would claim
    # "10000 records" for a search that actually matched far more.
    total = f"{result.total_hits}+" if result.total_is_capped else str(result.total_hits)

    notes = [f"Note: {note}" for note in result.notes]
    if not result.records:
        if result.offset > 0:
            message = f"No more {label} results for '{result.keyword}' at offset {result.offset}. Total found: {total}"
        else:
            message = f"No {label} results found for '{result.keyword}'."
        return "\n".join([message, *notes])

    lines: list[str] = [
        f"{label} search results for '{result.keyword}': showing {len(result.records)} of {total} records (offset {result.offset})",
        "",
    ]
    for rec in result.records:
        render_record(rec, lines)

    next_offset = result.offset + result.limit
    if next_offset < result.total_hits:
        lines.append(f"More results available. Use offset={next_offset} to see the next page.")
    lines.extend(notes)

    return "\n".join(lines)
