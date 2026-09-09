"""Search operations over the Diplomatarium Fennicum LanceDB table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import DEFAULT_LIMIT, DF_TABLE
from .dataset import DEFAULT_FUZZINESS, FTS_COLUMN, SearchResult, at_least, at_most, combine, equals, lancedb_fts_search, text_contains

if TYPE_CHECKING:
    import lancedb

__all__ = ["DfSearch", "SearchResult"]


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
            fuzzy: Edit distance allowed per term (default 1). Historical
                spelling is unstandardised, so exact matching finds one scribe's
                spelling and misses the rest. Pass 0 for an exact count.

        Returns:
            SearchResult with matching records.

        Raises:
            ValueError: If keyword is empty, offset is negative or limit < 1.
        """
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
        try:
            number = int(df_number)
        except (TypeError, ValueError):
            return None

        table = self._db.open_table(self._table_name)
        columns = [name for name in table.schema.names if name != FTS_COLUMN]
        rows = table.search().where(equals("df_number", number)).select(columns).limit(1).to_list()
        return rows[0] if rows else None
