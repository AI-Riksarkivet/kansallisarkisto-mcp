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
from .config import DF_TABLE, TUOMIOKIRJAT_TABLE, VOUDINTILIT_TABLE
from .dataset import FTS_COLUMN, build_fts_index, build_scalar_indexes
from .models import DfRecord, TuomiokirjatRecord, VoudintilitRecord

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

# No derived search column: the full-text index sits on `text` itself (see
# TuomiokirjatRecord). `volume_id` is int64 because these ids exceed 32 bits.
TUOMIOKIRJAT_SCHEMA = pa.schema(
    [
        pa.field("page_id", pa.string()),
        pa.field("volume_id", pa.int64()),
        pa.field("page", pa.int32()),
        pa.field("file_id", pa.string()),
        pa.field("collection", pa.string()),
        pa.field("series", pa.string()),
        pa.field("subseries", pa.string()),
        pa.field("unit", pa.string()),
        pa.field("reference", pa.string()),
        pa.field("year_start", pa.int32()),
        pa.field("year_end", pa.int32()),
        pa.field("year_from", pa.int32()),
        pa.field("year_to", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("url", pa.string()),
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
    keep: Callable[[BaseModel], bool] | None = None,
) -> Iterator[pa.RecordBatch]:
    """Stream an export as Arrow batches conforming to ``schema``.

    ``parse`` turns one source object into a record; when ``schema`` has the derived
    :data:`FTS_COLUMN`, the record's ``searchable_text`` property fills it. ``keep``
    may drop a parsed record — the de-duplication tuomiokirjat needs. A line that fails
    to parse is logged and skipped rather than aborting the run: these are harvested
    exports, and losing one malformed line is preferable to losing the whole ingest.
    """
    rows: list[dict[str, Any]] = []
    kept = skipped = dropped = 0
    derived = FTS_COLUMN in schema.names

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
            if keep is not None and not keep(record):
                dropped += 1
                continue
            flat = record.model_dump()
            if derived:
                flat[FTS_COLUMN] = record.searchable_text  # ty: ignore[unresolved-attribute]
            rows.append(flat)
            kept += 1

            if len(rows) >= batch_size:
                yield pa.RecordBatch.from_pylist(rows, schema=schema)
                rows = []

    if rows:
        yield pa.RecordBatch.from_pylist(rows, schema=schema)

    logger.info("Parsed %d %s records from %s (%d skipped, %d dropped as duplicates)", kept, corpus, jsonl_path, skipped, dropped)


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


def ingest_tuomiokirjat(
    db: lancedb.DBConnection,
    jsonl_path: str | Path,
    astia_path: str | Path | None = None,
    *,
    table_name: str = TUOMIOKIRJAT_TABLE,
    batch_size: int = BATCH_SIZE,
) -> lancedb.table.Table:
    """Ingest the tuomiokirjat export into a LanceDB table, one record per image.

    Sisältöhaku holds 60,000 images two or three times under distinct ids — the same
    link and years, usually the same text. The first occurrence of each ``(volume,
    page)`` is kept and the rest dropped, so no page is ever two hits. The set of
    pairs seen is the ingest's one in-memory structure: 7.8M small ints, under a
    gigabyte, on the machine that builds the table rather than the one that serves it.

    The Astia snapshot (``scripts/fetch_astia.py --metadata-only``) supplies each
    volume's signum; the export already carries every page's link. Without a snapshot
    the pages are ingested without a reference rather than dropped.

    The full-text index is built on ``text`` itself (see :class:`TuomiokirjatRecord`);
    the page lookup rides the ``page_id`` BTree, the neighbour lookup ``volume_id`` and
    ``page``.

    Raises:
        ValueError: If no records could be parsed from the export.
    """
    jsonl_path = Path(jsonl_path)
    volumes = load_snapshot(astia_path) if astia_path is not None else {}
    logger.info("Astia snapshot: %d volumes", len(volumes))

    def parse(row: dict[str, Any]) -> TuomiokirjatRecord:
        try:
            volume = volumes.get(int(row.get("ay_id")))  # ty: ignore[invalid-argument-type]
        except (TypeError, ValueError):
            volume = None
        return TuomiokirjatRecord.from_json(row, volume)

    seen: set[int] = set()

    def first_of_its_image(record: BaseModel) -> bool:
        assert isinstance(record, TuomiokirjatRecord)
        # A page whose number did not parse has no place in its volume to be a duplicate
        # of, and is kept: keying such rows on a blank file_id would drop every one of
        # them after the first. The rest pack into one int, so the set stays small.
        if record.page is None:
            return True
        key = (record.volume_id << 32) | record.page
        if key in seen:
            return False
        seen.add(key)
        return True

    batches = _record_batches(jsonl_path, parse, TUOMIOKIRJAT_SCHEMA, batch_size, "tuomiokirjat", keep=first_of_its_image)
    _create_table(db, table_name, TUOMIOKIRJAT_SCHEMA, batches, jsonl_path, "tuomiokirjat")

    # No bitmap on collection or series: both filters are substring LIKEs, which a
    # bitmap cannot serve, and on 7.7M rows the indexes would cost build time and disk
    # for nothing.
    build_fts_index(db, table_name, column="text")
    return build_scalar_indexes(db, table_name, btree=("page_id", "volume_id", "page", "year_from", "year_to"))
