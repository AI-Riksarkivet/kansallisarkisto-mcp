"""Shared fixtures: a LanceDB database holding the ingested df sample."""

from pathlib import Path

import lancedb
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df
from ra_mcp_kansallisarkisto_lib.search_operations import DfSearch

FIXTURES = Path(__file__).parent / "fixtures"
# 16 real Diplomatarium Fennicum records, chosen to cover the traps the corpus
# README documents: untranscribed charters, unknown years (0), unlocated places
# (null coordinates), open-ended and closed dating intervals, and all four main
# languages.
DF_FIXTURE = FIXTURES / "df_sample.jsonl"


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
