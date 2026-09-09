"""Tests for the df JSONL -> LanceDB ingest."""

import gzip
from pathlib import Path

import pyarrow as pa
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df

DF_FIXTURE = Path(__file__).parent / "fixtures" / "df_sample.jsonl"
DF_FIXTURE_ROWS = 16


def test_ingest_row_count(df_table):
    assert df_table.count_rows() == DF_FIXTURE_ROWS


def test_ingest_declares_schema(df_table):
    schema = df_table.schema
    for column in ("object_id", "df", "df_number", "transcript", "indexterm", "issuingplace", "issuingplacecountry", "language", "year_from", "year_to", "lat", "lng", "searchable_text"):
        assert column in schema.names, f"Missing column: {column}"
    # Declared, not inferred: with every charter in a batch unlocated, inference
    # would type these as null and break the merge with a later float batch.
    assert schema.field("lat").type == pa.float64()
    assert schema.field("df_number").type == pa.int32()


def test_ingest_builds_indexes(df_table):
    indexed = {idx.columns[0] for idx in df_table.list_indices()}
    assert "searchable_text" in indexed
    assert {"df_number", "year_from", "year_to", "language"} <= indexed


def test_ingest_reads_gzip(db, tmp_path):
    """The real export is df.jsonl.gz; the fixture is plain. Both must load."""
    gz = tmp_path / "df.jsonl.gz"
    gz.write_bytes(gzip.compress(DF_FIXTURE.read_bytes()))
    table = ingest_df(db, gz)
    assert table.count_rows() == DF_FIXTURE_ROWS


def test_ingest_skips_malformed_lines(db, tmp_path):
    jsonl = tmp_path / "broken.jsonl"
    jsonl.write_text(DF_FIXTURE.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    assert ingest_df(db, jsonl).count_rows() == DF_FIXTURE_ROWS


def test_ingest_empty_export_raises(db, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_df(db, empty)


def test_schema_and_model_cannot_drift_apart():
    """`from_pylist` with an explicit schema drops unknown keys silently.

    A field added to DfRecord without a matching column would therefore vanish
    at ingest with no error at all — this is the only thing that would notice.
    """
    from ra_mcp_kansallisarkisto_lib.dataset import FTS_COLUMN
    from ra_mcp_kansallisarkisto_lib.ingest import DF_SCHEMA
    from ra_mcp_kansallisarkisto_lib.models import DfRecord

    assert set(DfRecord.model_fields) | {FTS_COLUMN} == set(DF_SCHEMA.names)
