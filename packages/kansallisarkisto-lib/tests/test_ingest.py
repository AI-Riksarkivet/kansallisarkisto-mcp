"""Tests for the df JSONL -> LanceDB ingest."""

import gzip

import pyarrow as pa
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df

DF_FIXTURE_ROWS = 18


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


def test_ingest_reads_gzip(db, tmp_path, df_fixture):
    """The real export is df.jsonl.gz; the fixture is plain. Both must load."""
    gz = tmp_path / "df.jsonl.gz"
    gz.write_bytes(gzip.compress(df_fixture.read_bytes()))
    table = ingest_df(db, gz)
    assert table.count_rows() == DF_FIXTURE_ROWS


def test_ingest_skips_malformed_lines(db, tmp_path, df_fixture):
    jsonl = tmp_path / "broken.jsonl"
    jsonl.write_text(df_fixture.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
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


# --- voudintilit ----------------------------------------------------------------

VOUDINTILIT_FIXTURE_ROWS = 12


def _voudintilit_rows(table, *columns: str) -> dict[str, dict]:
    return {row["page_id"]: row for row in table.search().select(["page_id", *columns]).limit(1000).to_list()}


def test_voudintilit_ingest_row_count(voudintilit_table):
    assert voudintilit_table.count_rows() == VOUDINTILIT_FIXTURE_ROWS


def test_voudintilit_ingest_joins_the_astia_snapshot(voudintilit_table):
    rows = _voudintilit_rows(voudintilit_table, "reference", "url", "account_book")
    assert rows["1578628789_0016"]["reference"] == "2372"
    assert rows["1578628789_0016"]["url"] == "https://astia.narc.fi/uusiastia/viewer/?fileId=8489049831&aineistoId=1578628789"
    # Untitled in the export; Astia names it.
    assert rows["1580560161_0001"]["account_book"] == "Satakunnan voudintilien arkistoluettelo"


def test_voudintilit_ingest_without_a_snapshot_keeps_every_page(db, tmp_path, voudintilit_fixture):
    """The snapshot adds links; it must never be what decides whether a page exists."""
    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

    table = ingest_voudintilit(db, voudintilit_fixture, tmp_path / "absent.jsonl")
    assert table.count_rows() == VOUDINTILIT_FIXTURE_ROWS
    assert {row["url"] for row in _voudintilit_rows(table, "url").values()} == {""}


def test_voudintilit_join_does_not_depend_on_the_type_of_ay_id(db, tmp_path, voudintilit_fixture, voudintilit_astia_fixture):
    """The export sends ay_id as an int; a harvest that sent a string must not quietly
    lose every page link while the pages themselves still load."""
    import json

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

    rows = [json.loads(line) for line in voudintilit_fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    stringly = tmp_path / "stringly.jsonl"
    stringly.write_text("".join(json.dumps({**row, "ay_id": str(row["ay_id"])}, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    table = ingest_voudintilit(db, stringly, voudintilit_astia_fixture)
    assert "" not in {row["url"] for row in _voudintilit_rows(table, "url").values()}


def test_voudintilit_ingest_builds_indexes(voudintilit_table):
    indexed = {idx.columns[0] for idx in voudintilit_table.list_indices()}
    assert {"searchable_text", "volume_id", "page", "year_from", "year_to", "collection"} <= indexed


def test_voudintilit_ingest_reads_gzip(db, tmp_path, voudintilit_fixture, voudintilit_astia_fixture):
    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

    gz = tmp_path / "voudintilit.jsonl.gz"
    gz.write_bytes(gzip.compress(voudintilit_fixture.read_bytes()))
    assert ingest_voudintilit(db, gz, voudintilit_astia_fixture).count_rows() == VOUDINTILIT_FIXTURE_ROWS


def test_voudintilit_ingest_empty_export_raises(db, tmp_path):
    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_voudintilit(db, empty)


def test_voudintilit_schema_and_model_cannot_drift_apart():
    from ra_mcp_kansallisarkisto_lib.dataset import FTS_COLUMN
    from ra_mcp_kansallisarkisto_lib.ingest import VOUDINTILIT_SCHEMA
    from ra_mcp_kansallisarkisto_lib.models import VoudintilitRecord

    assert set(VoudintilitRecord.model_fields) | {FTS_COLUMN} == set(VOUDINTILIT_SCHEMA.names)
