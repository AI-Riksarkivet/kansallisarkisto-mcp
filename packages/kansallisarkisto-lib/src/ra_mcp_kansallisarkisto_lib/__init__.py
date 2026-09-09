"""Kansallisarkisto Sisältöhaku corpora — LanceDB ingest and full-text search."""

from .config import DEFAULT_LIMIT, DF_TABLE, MAX_LIMIT, resolve_lancedb_uri
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
from .ingest import ingest_df
from .models import DfRecord
from .search_operations import DfSearch

__all__ = [
    "DEFAULT_LIMIT",
    "DF_TABLE",
    "MAX_LIMIT",
    "MAX_TOTAL_COUNT",
    "DfRecord",
    "DfSearch",
    "SearchInputError",
    "SearchResult",
    "build_fts_index",
    "build_scalar_indexes",
    "format_results",
    "get_lancedb",
    "ingest_df",
    "lancedb_fts_search",
    "require_keyword",
    "require_ordered_range",
    "resolve_lancedb_uri",
    "table_names",
]
