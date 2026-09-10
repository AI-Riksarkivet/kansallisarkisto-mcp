"""Fetch Astia's metadata and image list for every voudintilit volume.

The Sisältöhaku export carries no link and no archival reference for a voudintilit page;
Astia has both (see ``ra_mcp_kansallisarkisto_lib.astia``). This makes two requests per
volume — 1,582 volumes, so about 3,200 — and appends one JSON line per volume to
``.data/voudintilit/astia.jsonl``.

Resumable: volumes already in the output are skipped, so an interrupted run continues
where it stopped. A volume Astia cannot serve is reported rather than written, so the
next run retries it.

    uv run python scripts/fetch_astia.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ra_mcp_kansallisarkisto_lib.astia import FILES_URL, METADATA_URL, load_snapshot, volume_entry

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / ".data" / "voudintilit" / "voudintilit.jsonl.gz"
SNAPSHOT = ROOT / ".data" / "voudintilit" / "astia.jsonl"
USER_AGENT = "kansallisarkisto-mcp (+https://github.com/AI-Riksarkivet/kansallisarkisto-mcp)"


def volume_ids(export: Path) -> list[int]:
    """Every distinct volume (``ay_id``) in the export."""
    ids: set[int] = set()
    with gzip.open(export, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                ids.add(int(json.loads(line)["ay_id"]))
    return sorted(ids)


def already_fetched(snapshot: Path) -> set[int]:
    """Volumes the snapshot already holds, read the way the ingest reads them — so a half
    line left by a killed run is skipped (and that volume fetched again), not fatal."""
    return set(load_snapshot(snapshot))


def end_with_newline(snapshot: Path) -> None:
    """Terminate a half-written last line, so the next entry is not glued onto it."""
    if snapshot.exists() and snapshot.stat().st_size:
        with snapshot.open("rb") as handle:
            handle.seek(-1, 2)
            if handle.read(1) != b"\n":
                with snapshot.open("a", encoding="utf-8") as out:
                    out.write("\n")


def get_json(url: str, *, retries: int = 4, timeout: float = 60.0) -> Any:
    """GET a JSON document, backing off 1, 2, 4, 8 s between failed attempts."""
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export", type=Path, default=EXPORT, help=f"voudintilit export (default: {EXPORT})")
    parser.add_argument("--output", type=Path, default=SNAPSHOT, help=f"snapshot to append to (default: {SNAPSHOT})")
    parser.add_argument("--sleep", type=float, default=0.5, help="seconds between requests (default: 0.5)")
    args = parser.parse_args()

    done = already_fetched(args.output)
    todo = [volume_id for volume_id in volume_ids(args.export) if volume_id not in done]
    print(f"{len(done)} volumes already fetched, {len(todo)} to go", file=sys.stderr)

    end_with_newline(args.output)
    failed: list[tuple[int, str]] = []
    with args.output.open("a", encoding="utf-8") as out:
        for count, volume_id in enumerate(todo, start=1):
            try:
                metadata = get_json(METADATA_URL.format(volume_id=volume_id))
                time.sleep(args.sleep)
                files = get_json(FILES_URL.format(volume_id=volume_id))
                time.sleep(args.sleep)
                entry = volume_entry(volume_id, metadata, files)
            except Exception as exc:  # noqa: BLE001 - one bad volume must not end a 3,200-request run
                failed.append((volume_id, f"{type(exc).__name__}: {exc}"))
                continue
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            out.flush()
            if count % 100 == 0:
                print(f"  {count}/{len(todo)}", file=sys.stderr)

    print(f"done: {len(todo) - len(failed)} fetched, {len(failed)} failed", file=sys.stderr)
    for volume_id, reason in failed:
        print(f"  failed {volume_id}: {reason}", file=sys.stderr)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
