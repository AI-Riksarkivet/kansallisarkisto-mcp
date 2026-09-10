"""Search operations over the Sisältöhaku LanceDB tables."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .config import DEFAULT_LIMIT, DF_TABLE, VOUDINTILIT_TABLE
from .dataset import DEFAULT_FUZZINESS, FTS_COLUMN, SearchInputError, SearchResult, at_least, at_most, combine, equals, lancedb_fts_search, text_contains
from .telemetry import get_tracer

if TYPE_CHECKING:
    import lancedb

__all__ = ["VOUDINTILIT_COLLECTIONS", "DfSearch", "SearchResult", "VoudintilitSearch"]

# The operations layer: one span per public method, nesting the spine's `search df`
# span underneath. It is the layer that knows *what was asked* (which filters, in
# the caller's terms) as opposed to *what was run* (a SQL predicate), so the
# filter-shaped attributes belong here rather than on the query span.
_tracer = get_tracer("kansallisarkisto.df.operations")


class DfSearch:
    """Full-text search and charter lookup over the ``df`` table."""

    def __init__(self, db: lancedb.DBConnection, *, table_name: str = DF_TABLE) -> None:
        self._db = db
        self._table_name = table_name

    def search(
        self,
        keyword: str,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        language: str | None = None,
        issuingplace: str | None = None,
        country: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        match_all: bool = True,
        fuzzy: int = DEFAULT_FUZZINESS,
    ) -> SearchResult:
        """Search the df table, optionally narrowed by catalogue metadata.

        The year filter is an interval-overlap test over the derived ``year_from``
        / ``year_to`` columns, not a comparison against ``dating_end_year``.
        Written the obvious way — ``dating_end_year <= year_max`` — a date-bounded
        search would match at most 33 of 6,876 charters, because 6,843 of them
        have no end year and SQL excludes NULLs from comparisons. Overlap over the
        closed interval is the correct question anyway: "which charters could have
        been issued in this window".

        Args:
            keyword: Search term (required, non-empty). Use period spelling —
                ``bref`` not ``brev``, ``Åbo`` not ``Turku``.
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).
            language: Exact language label, in unaccented Finnish (``ruotsi``,
                ``latina``, ``saksa``, ``venaja``).
            issuingplace: Case-insensitive substring of the place of issue, in its
                historical form (``Åbo``, ``Stockholm``, ``Rom``).
            country: Case-insensitive substring of the country of issue, in
                Finnish (``Suomi``, ``Ruotsi``, ``Italia``).
            year_min: Earliest year the charter may fall in.
            year_max: Latest year the charter may fall in.
            match_all: Require every word of the keyword (the default). False
                widens to any word, which helps when a term may be spelled
                differently but makes the total far less meaningful.
            fuzzy: Edit distance allowed per term; 0 by default, because fuzzy
                matching and stemming are mutually exclusive in the engine.
                Historical spelling is unstandardised, so raising it to 1 reaches
                variants a single spelling misses — best on a base form. Cannot
                be combined with a quoted phrase.

        Returns:
            SearchResult with matching records.

        Raises:
            ValueError: If keyword is empty, offset is negative or limit < 1.
        """
        # Only filters the caller actually set are recorded: an attribute set to
        # None on every unfiltered search is noise that costs storage per span.
        attributes = {
            "df.keyword": keyword,
            "df.limit": limit,
            "df.offset": offset,
            "df.match_all": match_all,
            "df.fuzzy": fuzzy,
            **({"df.language": language} if language else {}),
            **({"df.issuingplace": issuingplace} if issuingplace else {}),
            **({"df.country": country} if country else {}),
            **({"df.year_min": year_min} if year_min is not None else {}),
            **({"df.year_max": year_max} if year_max is not None else {}),
        }
        with _tracer.start_as_current_span("DfSearch.search", attributes=attributes):
            where = combine(
                equals("language", language) if language else None,
                text_contains("issuingplace", issuingplace) if issuingplace else None,
                text_contains("issuingplacecountry", country) if country else None,
                at_least("year_to", year_min) if year_min is not None else None,
                at_most("year_from", year_max) if year_max is not None else None,
            )
            return lancedb_fts_search(self._db, self._table_name, keyword, limit=limit, offset=offset, where=where, match_all=match_all, fuzzy=fuzzy)

    def get_charter(self, df_number: str | int) -> dict[str, Any] | None:
        """Return one charter by its DF number, or ``None`` if there is no such charter.

        The DF number is the citable identifier a researcher quotes ("DF 1451"),
        so this is the lookup that follows a search hit. Backed by the ``df_number``
        BTree index, hence a page lookup rather than a scan.

        Projects out the same full-text column ``search`` does, so a record dict
        has the same shape whichever way the caller obtained it.
        """
        with _tracer.start_as_current_span("DfSearch.get_charter", attributes={"df.number": str(df_number)}) as span:
            try:
                number = int(df_number)
            except (TypeError, ValueError):
                span.set_attribute("df.found", False)
                return None
            # df_number is an int32 column: a value outside its range cannot be a
            # charter, and letting the predicate fail turns an ordinary out-of-range
            # lookup into "the search failed with an internal ValueError".
            if not -(2**31) <= number < 2**31:
                span.set_attribute("df.found", False)
                return None

            table = self._db.open_table(self._table_name)
            columns = [name for name in table.schema.names if name != FTS_COLUMN]
            rows = table.search().where(equals("df_number", number)).select(columns).limit(1).to_list()
            # A miss is a normal answer, not an error — but it is the thing worth
            # counting when models cite DF numbers that do not exist.
            span.set_attribute("df.found", bool(rows))
            return rows[0] if rows else None


# The collection filter's choices, mapped to the source's labels. The labels are Finnish
# genitives — "Satakunnan voutikuntien tilejä" — which the obvious substring "Satakunta"
# does not match, so the filter is a fixed choice rather than free text.
VOUDINTILIT_COLLECTIONS = {
    "hame": "Hämeen voutikuntien tilejä",
    "satakunta": "Satakunnan voutikuntien tilejä",
}

# A page id is the source's objectID, "<volume>_<page>" ("1578628789_0016"). Bounded to
# what the int64 and int32 columns can hold — int() refuses strings past 4,300 digits,
# which would otherwise surface as an internal error — and [0-9] rather than \d, which
# would admit non-ASCII digits.
_PAGE_ID = re.compile(r"^([0-9]{1,19})_([0-9]{1,10})$")

# No volume holds more than 628 pages; this only has to exceed that.
_MAX_PAGES_PER_VOLUME = 10_000

_voudintilit_tracer = get_tracer("kansallisarkisto.voudintilit.operations")


class VoudintilitSearch:
    """Full-text search and page lookup over the ``voudintilit`` table."""

    def __init__(self, db: lancedb.DBConnection, *, table_name: str = VOUDINTILIT_TABLE) -> None:
        self._db = db
        self._table_name = table_name

    def search(
        self,
        keyword: str,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        collection: str | None = None,
        account_book: str | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        match_all: bool = True,
        fuzzy: int = DEFAULT_FUZZINESS,
    ) -> SearchResult:
        """Search the bailiff-account pages, optionally narrowed by collection, account
        book and year.

        Args:
            keyword: Search term (required, non-empty), in early-modern Swedish spelling.
            limit: Maximum number of results to return.
            offset: Number of results to skip (for pagination).
            collection: ``hame`` or ``satakunta`` — see :data:`VOUDINTILIT_COLLECTIONS`.
            account_book: Case-insensitive substring of the account book's title
                (``Sääksmäen``, ``Hämeen linnan``, ``Maakirja``).
            year_min: Earliest year the page may fall in.
            year_max: Latest year the page may fall in.
            match_all: Require every word of the keyword (the default).
            fuzzy: Edit distance allowed per term; see :meth:`DfSearch.search`.

        Returns:
            SearchResult with matching pages.

        Raises:
            SearchInputError: For an unknown collection, as well as the spine's guards.
        """
        label = None
        if collection is not None:
            label = VOUDINTILIT_COLLECTIONS.get(collection.strip().lower())
            if label is None:
                raise SearchInputError(f"collection must be one of {', '.join(sorted(VOUDINTILIT_COLLECTIONS))} (got {collection!r})")

        attributes = {
            "voudintilit.keyword": keyword,
            "voudintilit.limit": limit,
            "voudintilit.offset": offset,
            "voudintilit.match_all": match_all,
            "voudintilit.fuzzy": fuzzy,
            **({"voudintilit.collection": collection} if collection else {}),
            **({"voudintilit.account_book": account_book} if account_book else {}),
            **({"voudintilit.year_min": year_min} if year_min is not None else {}),
            **({"voudintilit.year_max": year_max} if year_max is not None else {}),
        }
        with _voudintilit_tracer.start_as_current_span("VoudintilitSearch.search", attributes=attributes):
            where = combine(
                equals("collection", label) if label else None,
                text_contains("account_book", account_book) if account_book else None,
                at_least("year_to", year_min) if year_min is not None else None,
                at_most("year_from", year_max) if year_max is not None else None,
            )
            return lancedb_fts_search(self._db, self._table_name, keyword, limit=limit, offset=offset, where=where, match_all=match_all, fuzzy=fuzzy)

    def get_page(self, page_id: str) -> dict[str, Any] | None:
        """Return one page by its id, or ``None`` if there is no such page.

        The record carries two extra keys, ``previous_page_id`` and ``next_page_id``:
        the volume's nearest existing pages on either side, or ``None`` at its ends.
        Nearest *existing*, because 106 volumes have gaps — Astia holds images
        Sisältöhaku has no text for — so page N's neighbour is not always N ± 1.

        Looked up as ``volume_id`` + ``page`` rather than by ``page_id`` so both
        queries ride the BTree indexes; the neighbour query reads one volume's page
        numbers, at most a few hundred rows.
        """
        with _voudintilit_tracer.start_as_current_span("VoudintilitSearch.get_page", attributes={"voudintilit.page_id": str(page_id)}) as span:
            match = _PAGE_ID.match(page_id.strip()) if isinstance(page_id, str) else None
            volume_id, page = (int(match.group(1)), int(match.group(2))) if match else (None, None)
            # volume_id is int64 and page int32: a number outside either cannot be a
            # page, and letting the predicate fail would report an ordinary miss as an
            # internal error.
            if volume_id is None or page is None or volume_id >= 2**63 or page >= 2**31:
                span.set_attribute("voudintilit.found", False)
                return None

            table = self._db.open_table(self._table_name)
            columns = [name for name in table.schema.names if name != FTS_COLUMN]
            rows = table.search().where(f"{equals('volume_id', volume_id)} AND {equals('page', page)}").select(columns).limit(1).to_list()
            span.set_attribute("voudintilit.found", bool(rows))
            if not rows:
                return None

            record = rows[0]
            siblings = table.search().where(equals("volume_id", volume_id)).select(["page", "page_id"]).limit(_MAX_PAGES_PER_VOLUME).to_list()
            ordered = sorted((row["page"], row["page_id"]) for row in siblings if row["page"] is not None)
            earlier = [pid for number, pid in ordered if number < page]
            later = [pid for number, pid in ordered if number > page]
            record["previous_page_id"] = earlier[-1] if earlier else None
            record["next_page_id"] = later[0] if later else None
            return record
