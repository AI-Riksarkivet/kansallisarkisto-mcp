"""Ingest the Diplomatarium Fennicum export into a LanceDB table.

Usage:
    uv run python scripts/ingest_df.py [--jsonl PATH] [--output PATH]

Reads the harvested export from .data/df/df.jsonl.gz by default and writes the
`df` table into the LanceDB database at data/ — both git-ignored.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import lancedb

from ra_mcp_kansallisarkisto_lib.config import DF_TABLE, resolve_lancedb_uri
from ra_mcp_kansallisarkisto_lib.ingest import ingest_df

DEFAULT_JSONL = Path(".data/df/df.jsonl.gz")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Diplomatarium Fennicum into LanceDB")
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL, help=f"Path to the df export (default: {DEFAULT_JSONL})")
    parser.add_argument("--output", type=Path, default=None, help="LanceDB database path (default: the resolved KA_LANCEDB_URI / data/)")
    args = parser.parse_args()

    if not args.jsonl.exists():
        raise SystemExit(f"Export not found: {args.jsonl}\nHarvest it from sisaltohaku.demo.kansallisarkisto.fi, or pass --jsonl.")

    output = args.output or Path(resolve_lancedb_uri())
    output.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(output)

    logger.info("Ingesting %s ...", args.jsonl)
    table = ingest_df(db, args.jsonl)
    logger.info("Table '%s' at %s: %d rows", DF_TABLE, output, table.count_rows())


if __name__ == "__main__":
    main()
