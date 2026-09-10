"""Shared fixtures: a LanceDB database holding the ingested df sample."""

from pathlib import Path

import lancedb
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df
from ra_mcp_kansallisarkisto_lib.search_operations import DfSearch

FIXTURES = Path(__file__).parent / "fixtures"
# 19 real Diplomatarium Fennicum records, chosen to cover the traps the corpus
# README documents: untranscribed charters, unknown years (0), unlocated places
# (null coordinates), open-ended and closed dating intervals, and all four main
# languages — and DF 173, a charter about Reval with no recorded place of issue.
DF_FIXTURE = FIXTURES / "df_sample.jsonl"
# 12 real voudintilit pages from 6 volumes: both collections, both sides of a page
# gap (1576091152 has no page 2), neighbouring pages (1578628789 p. 15–17, 1570685252
# p. 13–15), the inverted-year volume (1615–1516), the untitled catalogue volume with
# unknown years, and an empty page. With it, the Astia snapshot lines for those volumes.
VOUDINTILIT_FIXTURE = FIXTURES / "voudintilit_sample.jsonl"
VOUDINTILIT_ASTIA_FIXTURE = FIXTURES / "voudintilit_astia_sample.jsonl"


@pytest.fixture
def voudintilit_fixture() -> Path:
    return VOUDINTILIT_FIXTURE


@pytest.fixture
def voudintilit_astia_fixture() -> Path:
    return VOUDINTILIT_ASTIA_FIXTURE


@pytest.fixture
def df_fixture() -> Path:
    """The sample export path, so test modules need not each rebuild it."""
    return DF_FIXTURE


@pytest.fixture
def df_fixture_records(df_fixture) -> list[dict]:
    """The sample export parsed, for tests that reason about the data itself."""
    import json

    return [json.loads(line) for line in df_fixture.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def db(tmp_path):
    return lancedb.connect(str(tmp_path / "test.lance"))


@pytest.fixture
def df_table(db):
    return ingest_df(db, DF_FIXTURE)


@pytest.fixture
def search(db, df_table):
    """A DfSearch backed by the ingested sample."""
    return DfSearch(db)


@pytest.fixture
def voudintilit_table(db):
    # Imported here rather than at the top so a module that does not ask for this
    # fixture never depends on it.
    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

    return ingest_voudintilit(db, VOUDINTILIT_FIXTURE, VOUDINTILIT_ASTIA_FIXTURE)


@pytest.fixture
def voudintilit_search(db, voudintilit_table):
    """A VoudintilitSearch backed by the ingested sample."""
    from ra_mcp_kansallisarkisto_lib.search_operations import VoudintilitSearch

    return VoudintilitSearch(db)
