"""Kansallisarkisto Sisältöhaku corpora — LanceDB ingest and full-text search."""

from .config import DEFAULT_LIMIT, DF_TABLE, MAX_LIMIT, TUOMIOKIRJAT_TABLE, VOUDINTILIT_TABLE, resolve_lancedb_uri, stage_lancedb
from .dataset import (
    MAX_TOTAL_COUNT,
    SearchInputError,
    SearchResult,
    build_fts_index,
    build_scalar_indexes,
    format_results,
    get_lancedb,
    lancedb_fts_search,
    require_keyword,
    require_ordered_range,
    table_names,
)
from .ingest import ingest_df, ingest_tuomiokirjat, ingest_voudintilit
from .models import DfRecord, TuomiokirjatRecord, VoudintilitRecord
from .search_operations import VOUDINTILIT_COLLECTIONS, DfSearch, TuomiokirjatSearch, VoudintilitSearch

__all__ = [
    "DEFAULT_LIMIT",
    "DF_TABLE",
    "MAX_LIMIT",
    "MAX_TOTAL_COUNT",
    "TUOMIOKIRJAT_TABLE",
    "VOUDINTILIT_COLLECTIONS",
    "VOUDINTILIT_TABLE",
    "DfRecord",
    "DfSearch",
    "SearchInputError",
    "SearchResult",
    "TuomiokirjatRecord",
    "TuomiokirjatSearch",
    "VoudintilitRecord",
    "VoudintilitSearch",
    "build_fts_index",
    "build_scalar_indexes",
    "format_results",
    "get_lancedb",
    "ingest_df",
    "ingest_tuomiokirjat",
    "ingest_voudintilit",
    "lancedb_fts_search",
    "require_keyword",
    "require_ordered_range",
    "resolve_lancedb_uri",
    "stage_lancedb",
    "table_names",
]
