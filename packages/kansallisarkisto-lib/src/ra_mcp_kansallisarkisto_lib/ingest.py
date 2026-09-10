"""Build the LanceDB tables from the harvested Sisältöhaku JSONL exports."""

from __future__ import annotations

import gzip
import itertools
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import pyarrow as pa

from .astia import load_snapshot
from .config import DF_TABLE, VOUDINTILIT_TABLE
from .dataset import build_fts_index, build_scalar_indexes
from .models import DfRecord, VoudintilitRecord

if TYPE_CHECKING:
    import lancedb
    from pydantic import BaseModel

logger = logging.getLogger(__name__)

# The schema is declared rather than inferred. Inference reads a sample and would
# type `lat`/`lng` as null for any batch where every charter is unlocated (2,734
# of 6,876 are), which then fails to merge with a later batch that has floats.
# Declaring it also pins the column types across corpora — `file_id` is a
# zero-padded string in voudintilit and an integer in tuomiokirjat, so inference
# would disagree with itself between the two tables.
DF_SCHEMA = pa.schema(
    [
        pa.field("object_id", pa.string()),
        pa.field("df", pa.string()),
        pa.field("df_number", pa.int32()),
        pa.field("transcript", pa.string()),
        pa.field("indexterm", pa.string()),
        pa.field("issuingplace", pa.string()),
        pa.field("issuingplacecountry", pa.string()),
        pa.field("language", pa.string()),
        pa.field("dating_start_year", pa.int32()),
        pa.field("dating_end_year", pa.int32()),
        pa.field("year_from", pa.int32()),
        pa.field("year_to", pa.int32()),
        pa.field("lat", pa.float64()),
        pa.field("lng", pa.float64()),
        pa.field("searchable_text", pa.string()),
    ]
)

# `volume_id` is int64 although every voudintilit volume id fits in 32 bits:
# tuomiokirjat's do not (2,320,246,345), and the two tables should agree on the type
# of the column they share.
VOUDINTILIT_SCHEMA = pa.schema(
    [
        pa.field("page_id", pa.string()),
        pa.field("volume_id", pa.int64()),
        pa.field("page", pa.int32()),
        pa.field("file_id", pa.string()),
        pa.field("collection", pa.string()),
        pa.field("account_book", pa.string()),
        pa.field("reference", pa.string()),
        pa.field("series", pa.string()),
        pa.field("year_start", pa.int32()),
        pa.field("year_end", pa.int32()),
        pa.field("year_from", pa.int32()),
        pa.field("year_to", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("url", pa.string()),
        pa.field("searchable_text", pa.string()),
    ]
)

# Rows per Arrow batch handed to LanceDB. Small enough that the 19 GB
# tuomiokirjat export never has to be materialised in memory, large enough that
# per-batch overhead stays negligible on the 6,876-row df corpus.
BATCH_SIZE = 5_000


def _open_jsonl(path: Path) -> IO[str]:
    """Open a JSONL export, transparently decompressing a ``.gz``."""
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def _record_batches(
    jsonl_path: Path,
    parse: Callable[[dict[str, Any]], BaseModel],
    schema: pa.Schema,
    batch_size: int,
    corpus: str,
) -> Iterator[pa.RecordBatch]:
    """Stream an export as Arrow batches conforming to ``schema``.

    ``parse`` turns one source object into a record carrying a ``searchable_text``
    property. A line that fails to parse is logged and skipped rather than aborting the
    run: these are harvested exports, and losing one malformed line is preferable to
    losing the whole ingest.
    """
    rows: list[dict[str, Any]] = []
    kept = skipped = 0

    with _open_jsonl(jsonl_path) as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise TypeError(f"expected a JSON object, got {type(data).__name__}")
                record = parse(data)
            except (ValueError, TypeError) as exc:
                # ValueError covers both json.JSONDecodeError and pydantic's
                # ValidationError. Anything outside those two (a MemoryError on a
                # 19 GB export, a KeyboardInterrupt) is not a bad line and must
                # not be swallowed as one.
                logger.warning("Skipping %s line %d: %s", jsonl_path.name, lineno, exc)
                skipped += 1
                continue
            flat = record.model_dump()
            flat["searchable_text"] = record.searchable_text  # ty: ignore[unresolved-attribute]
            rows.append(flat)
            kept += 1

            if len(rows) >= batch_size:
                yield pa.RecordBatch.from_pylist(rows, schema=schema)
                rows = []

    if rows:
        yield pa.RecordBatch.from_pylist(rows, schema=schema)

    logger.info("Parsed %d %s records from %s (%d skipped)", kept, corpus, jsonl_path, skipped)


def _create_table(
    db: lancedb.DBConnection,
    table_name: str,
    schema: pa.Schema,
    batches: Iterator[pa.RecordBatch],
    jsonl_path: Path,
    corpus: str,
) -> None:
    """Write the batches to a fresh table, failing plainly on an empty export."""
    # Pull the first batch before handing the stream to LanceDB. An empty export
    # has to fail as a plain ValueError here; raised from inside the reader it
    # would surface as an Arrow C-interface RuntimeError with the real message
    # buried in a traceback, after a half-created table.
    first = next(batches, None)
    if first is None:
        raise ValueError(f"No valid {corpus} records parsed from {jsonl_path}")

    # RecordBatchReader keeps the ingest streaming: LanceDB pulls batches as it
    # writes, so peak memory is one batch rather than the whole corpus.
    reader = pa.RecordBatchReader.from_batches(schema, itertools.chain([first], batches))
    db.create_table(table_name, data=reader, schema=schema, mode="overwrite")


def ingest_df(
    db: lancedb.DBConnection,
    jsonl_path: str | Path,
    *,
    table_name: str = DF_TABLE,
    batch_size: int = BATCH_SIZE,
) -> lancedb.table.Table:
    """Ingest the Diplomatarium Fennicum export into a LanceDB table.

    Builds the table, then the Swedish full-text index over ``searchable_text``
    and the scalar indexes the tool's filters push down to.

    Args:
        db: LanceDB database connection.
        jsonl_path: Path to ``df.jsonl.gz`` (or an uncompressed ``.jsonl``).
        table_name: Table to create; overridable for tests.
        batch_size: Rows per Arrow batch.

    Returns:
        The table handle carrying the finished indexes.

    Raises:
        ValueError: If no records could be parsed from the export.
    """
    jsonl_path = Path(jsonl_path)
    batches = _record_batches(jsonl_path, DfRecord.from_json, DF_SCHEMA, batch_size, "df")
    _create_table(db, table_name, DF_SCHEMA, batches, jsonl_path, "df")

    build_fts_index(db, table_name)
    return build_scalar_indexes(
        db,
        table_name,
        btree=("df_number", "year_from", "year_to"),
        bitmap=("language", "issuingplacecountry"),
    )


def ingest_voudintilit(
    db: lancedb.DBConnection,
    jsonl_path: str | Path,
    astia_path: str | Path | None = None,
    *,
    table_name: str = VOUDINTILIT_TABLE,
    batch_size: int = BATCH_SIZE,
) -> lancedb.table.Table:
    """Ingest the voudintilit export into a LanceDB table, joined with the Astia snapshot.

    The snapshot (``scripts/fetch_astia.py``) supplies each volume's archival reference
    and each page's viewer link. Without it — or for a volume it lacks — pages are
    ingested without them rather than dropped: the snapshot adds citations, it does not
    decide what exists.

    Args:
        db: LanceDB database connection.
        jsonl_path: Path to ``voudintilit.jsonl.gz`` (or an uncompressed ``.jsonl``).
        astia_path: Path to ``astia.jsonl``; ``None`` or a missing file means no links.
        table_name: Table to create; overridable for tests.
        batch_size: Rows per Arrow batch.

    Returns:
        The table handle carrying the finished indexes.

    Raises:
        ValueError: If no records could be parsed from the export.
    """
    jsonl_path = Path(jsonl_path)
    volumes = load_snapshot(astia_path) if astia_path is not None else {}
    logger.info("Astia snapshot: %d volumes", len(volumes))

    def parse(row: dict[str, Any]) -> VoudintilitRecord:
        # Joined on the parsed volume id — the same int the record stores — so a harvest
        # that sent ay_id as a string cannot quietly lose every link. A value that does
        # not parse fails again in from_json, which skips the line.
        try:
            volume = volumes.get(int(row.get("ay_id")))  # ty: ignore[invalid-argument-type]
        except (TypeError, ValueError):
            volume = None
        return VoudintilitRecord.from_json(row, volume)

    batches = _record_batches(jsonl_path, parse, VOUDINTILIT_SCHEMA, batch_size, "voudintilit")
    _create_table(db, table_name, VOUDINTILIT_SCHEMA, batches, jsonl_path, "voudintilit")

    # Early-modern Swedish, so the df analyser settings apply unchanged. The page lookup
    # (volume_id + page) and the neighbour lookup ride the two BTrees.
    build_fts_index(db, table_name)
    return build_scalar_indexes(
        db,
        table_name,
        btree=("volume_id", "page", "year_from", "year_to"),
        bitmap=("collection",),
    )
