"""Shared fixtures for the MCP-layer tests."""

from pathlib import Path

import lancedb
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df
from ra_mcp_kansallisarkisto_lib.search_operations import DfSearch

# The same 18-charter sample the lib tests use, so the two layers are exercised
# against identical data.
DF_FIXTURE = Path(__file__).parents[2] / "kansallisarkisto-lib" / "tests" / "fixtures" / "df_sample.jsonl"


@pytest.fixture
def df_fixture() -> Path:
    """The sample export path, so test modules need not each rebuild it."""
    return DF_FIXTURE


@pytest.fixture
def df_search(tmp_path):
    db = lancedb.connect(str(tmp_path / "test.lance"))
    ingest_df(db, DF_FIXTURE)
    return DfSearch(db)
