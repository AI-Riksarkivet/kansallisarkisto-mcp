"""Ingest the voudintilit (bailiff accounts) export into a LanceDB table.

Usage:
    uv run python scripts/ingest_voudintilit.py [--jsonl PATH] [--astia PATH] [--output PATH]

Reads the harvested export from .data/voudintilit/voudintilit.jsonl.gz and the Astia
snapshot beside it (scripts/fetch_astia.py), and writes the `voudintilit` table into the
LanceDB database at data/ — all git-ignored. Without the snapshot the pages are still
ingested, but carry no archival reference and no page link.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import lancedb

from ra_mcp_kansallisarkisto_lib.config import VOUDINTILIT_TABLE, resolve_lancedb_uri
from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

DEFAULT_JSONL = Path(".data/voudintilit/voudintilit.jsonl.gz")
DEFAULT_ASTIA = Path(".data/voudintilit/astia.jsonl")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest voudintilit into LanceDB")
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL, help=f"Path to the voudintilit export (default: {DEFAULT_JSONL})")
    parser.add_argument("--astia", type=Path, default=DEFAULT_ASTIA, help=f"Path to the Astia snapshot (default: {DEFAULT_ASTIA})")
    parser.add_argument("--output", type=Path, default=None, help="LanceDB database path (default: the resolved KA_LANCEDB_URI / data/)")
    args = parser.parse_args()

    if not args.jsonl.exists():
        raise SystemExit(f"Export not found: {args.jsonl}\nHarvest it with `uv run python scripts/harvest.py --index voudintilit`, or pass --jsonl.")
    if not args.astia.exists():
        logger.warning("No Astia snapshot at %s — pages will have no reference or link. Run scripts/fetch_astia.py first.", args.astia)

    output = args.output or Path(resolve_lancedb_uri())
    output.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(output)

    logger.info("Ingesting %s ...", args.jsonl)
    table = ingest_voudintilit(db, args.jsonl, args.astia)
    logger.info("Table '%s' at %s: %d rows", VOUDINTILIT_TABLE, output, table.count_rows())


if __name__ == "__main__":
    main()
