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
import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from lancedb.index import FTS, Bitmap, BTree
from lancedb.query import FullTextOperator, MatchQuery
from pydantic import BaseModel

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
    column: str = "searchable_text",
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

    matches = query.limit(MAX_TOTAL_COUNT).to_list()
    total = len(matches)
    page = matches[offset : offset + limit]

    return SearchResult(
        records=page,
        total_hits=total,
        keyword=keyword,
        offset=offset,
        limit=limit,
        total_is_capped=total >= MAX_TOTAL_COUNT,
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

    if not result.records:
        if result.offset > 0:
            return f"No more {label} results for '{result.keyword}' at offset {result.offset}. Total found: {total}"
        return f"No {label} results found for '{result.keyword}'."

    lines: list[str] = [
        f"{label} search results for '{result.keyword}': showing {len(result.records)} of {total} records (offset {result.offset})",
        "",
    ]
    for rec in result.records:
        render_record(rec, lines)

    next_offset = result.offset + result.limit
    if next_offset < result.total_hits:
        lines.append(f"More results available. Use offset={next_offset} to see the next page.")

    return "\n".join(lines)
