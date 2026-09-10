"""Ingest the tuomiokirjat (court records) export into a LanceDB table.

Usage:
    uv run python scripts/ingest_tuomiokirjat.py [--jsonl PATH] [--astia PATH] [--output PATH]

Reads the harvested export from .data/tuomiokirjat/tuomiokirjat.jsonl.gz and the Astia
snapshot beside it (scripts/fetch_astia.py --metadata-only), and writes the `tuomiokirjat`
table into the LanceDB database at data/ — all git-ignored. One record per image: the
60,000 images Sisältöhaku holds twice are kept once. Without the snapshot the pages are
still ingested, but carry no signum.

The full-text index over 7.8 million pages is built with one shard and 256 MiB partitions
— set below, before lance is imported, because lance reads them once at first use. With
its defaults (a shard per CPU, larger partitions) the build of the 1M-page trial peaked at
5.8 GiB and the full corpus was killed at 12 GiB; with these the full corpus built in 18
minutes with a 6.6 GiB peak, 11 GB of data and 11 GB of index — and the index came out
smaller than with the defaults too.
"""

from __future__ import annotations

import os

os.environ.setdefault("LANCE_FTS_NUM_SHARDS", "1")
os.environ.setdefault("LANCE_FTS_PARTITION_SIZE", "256")

import argparse
import logging
from pathlib import Path

import lancedb

from ra_mcp_kansallisarkisto_lib.config import TUOMIOKIRJAT_TABLE, resolve_lancedb_uri
from ra_mcp_kansallisarkisto_lib.ingest import ingest_tuomiokirjat

DEFAULT_JSONL = Path(".data/tuomiokirjat/tuomiokirjat.jsonl.gz")
DEFAULT_ASTIA = Path(".data/tuomiokirjat/astia.jsonl")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest tuomiokirjat into LanceDB")
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL, help=f"Path to the tuomiokirjat export (default: {DEFAULT_JSONL})")
    parser.add_argument("--astia", type=Path, default=DEFAULT_ASTIA, help=f"Path to the Astia snapshot (default: {DEFAULT_ASTIA})")
    parser.add_argument("--output", type=Path, default=None, help="LanceDB database path (default: the resolved KA_LANCEDB_URI / data/)")
    args = parser.parse_args()

    if not args.jsonl.exists():
        raise SystemExit(f"Export not found: {args.jsonl}\nHarvest it with `uv run python scripts/harvest.py --index tuomiokirjat` (about 1.5 h, 6.3 GB), or pass --jsonl.")
    if not args.astia.exists():
        logger.warning("No Astia snapshot at %s — pages will have no signum. Run `make fetch-astia-tuomiokirjat` first.", args.astia)

    output = args.output or Path(resolve_lancedb_uri())
    output.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(output)

    logger.info("Ingesting %s ...", args.jsonl)
    table = ingest_tuomiokirjat(db, args.jsonl, args.astia)
    logger.info("Table '%s' at %s: %d rows", TUOMIOKIRJAT_TABLE, output, table.count_rows())


if __name__ == "__main__":
    main()
