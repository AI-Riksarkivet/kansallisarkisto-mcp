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


# The lib tests' 12-page voudintilit sample and its Astia snapshot.
VOUDINTILIT_FIXTURE = DF_FIXTURE.parent / "voudintilit_sample.jsonl"
VOUDINTILIT_ASTIA_FIXTURE = DF_FIXTURE.parent / "voudintilit_astia_sample.jsonl"


@pytest.fixture
def voudintilit_fixture() -> Path:
    return VOUDINTILIT_FIXTURE


@pytest.fixture
def voudintilit_astia_fixture() -> Path:
    return VOUDINTILIT_ASTIA_FIXTURE


@pytest.fixture
def voudintilit_search(tmp_path):
    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit
    from ra_mcp_kansallisarkisto_lib.search_operations import VoudintilitSearch

    db = lancedb.connect(str(tmp_path / "voudintilit.lance"))
    ingest_voudintilit(db, VOUDINTILIT_FIXTURE, VOUDINTILIT_ASTIA_FIXTURE)
    return VoudintilitSearch(db)
