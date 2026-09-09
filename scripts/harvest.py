"""Re-harvest the Sisältöhaku corpora from Kansallisarkisto's demo service.

Usage:
    uv run python scripts/harvest.py --index df
    uv run python scripts/harvest.py --index all --output .data
    uv run python scripts/harvest.py --index tuomiokirjat --resume

Writes, per corpus, exactly what `.data/` already holds — so a re-harvest is a
drop-in replacement for the snapshot the ingest reads:

    <output>/<index>/<index>.jsonl.gz   one JSON object per line, UTF-8
    <output>/<index>/checkpoint.json    {"done": [...slice keys...], "shortfalls": [...]}
    <output>/<index>/report.json        coverage summary

## The service

Two public JSON endpoints behind the Sisältöhaku frontend, both POST:

`/api/search` takes a bare array of Algolia-style requests and answers with true,
uncapped counts and facet values::

    [{"indexName": "voudintilit",
      "params": {"hitsPerPage": 0, "facets": ["Aineistokokonaisuus_vt"],
                 "facetFilters": [["Aineistokokonaisuus_vt:Hämeen voutikuntien tilejä"]],
                 "numericFilters": ["alkuvuosi=1539"]}}]

`/api/export-all` returns the documents themselves, and is what the site's own
"download results" button calls::

    {"index": "voudintilit",
     "uiState": {"refinementList": {"Aineistokokonaisuus_vt": ["..."]},
                 "range": {"alkuvuosi": {"min": 1539, "max": 1539}}},
     "maxResults": 10000}

Two details about `uiState` are load-bearing and were established by probing the
live service, because getting either wrong fails silently — the filter is ignored
and the export returns an unfiltered page that looks perfectly valid:

- the year range must be the object form ``{"min": y, "max": y}``. The string form
  ``"1539:1539"`` that InstantSearch itself serialises is accepted and ignored.
- the collection facet name differs per corpus (``Aineistokokonaisuus`` vs
  ``Aineistokokonaisuus_vt``), see :data:`INDEXES`.

## Why the harvest is sliced

`/api/export-all` returns at most 10,000 documents per request — Elasticsearch's
``from + size`` ceiling — and its ``total`` saturates there too, so the response
cannot tell you whether you got everything. Counts therefore come from
`/api/search`, which is uncapped, and each slice is exported only once its true
size is known to fit.

The public frontend exposes exactly two filterable axes, so slicing escalates:

    whole index                 →  key "all"
    by start year               →  key "y=1539"
    by collection and year      →  key "c=<collection>|y=1539"

A cell that is still over the ceiling at the finest available split cannot be
subdivided any further. Those documents are unreachable by this route: the run
records a shortfall, takes the first 10,000, and reports the gap rather than
quietly returning a short file. 22 such cells existed at the July 2026 harvest,
141,032 documents in all — 1.75% of the corpus. The documented Elasticsearch API
at ``es.demo.kansallisarkisto.fi`` has no such ceiling; with an API key from
Kansallisarkisto those documents are retrievable and this script is the wrong tool.

## Resuming

Every completed slice is appended as its own gzip member and then recorded in
``checkpoint.json``, so ``--resume`` skips what is already on disk. A crash in the
window between those two steps re-fetches one slice and can duplicate it; the
corpora carry a unique ``objectID``, so ``--verify`` will find that if it happens.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_URL = "https://sisaltohaku.demo.kansallisarkisto.fi"
SEARCH_ENDPOINT = "/api/search"
EXPORT_ENDPOINT = "/api/export-all"

# Elasticsearch's from+size ceiling, and what /api/export-all enforces.
EXPORT_CEILING = 10_000

# The year facet is the same across all three corpora; the collection facet is not.
YEAR_ATTRIBUTE = "alkuvuosi"

logger = logging.getLogger("harvest")


@dataclass(frozen=True)
class IndexSpec:
    """How one corpus is filtered and sliced."""

    name: str
    # Collection facet attribute, or None for a corpus small enough to take whole.
    collection_attribute: str | None


INDEXES: dict[str, IndexSpec] = {
    # 6,876 documents — comfortably under the ceiling, so it needs no slicing at all.
    "df": IndexSpec("df", collection_attribute=None),
    "voudintilit": IndexSpec("voudintilit", collection_attribute="Aineistokokonaisuus_vt"),
    "tuomiokirjat": IndexSpec("tuomiokirjat", collection_attribute="Aineistokokonaisuus"),
}


@dataclass
class Slice:
    """One unit of work: a filter narrow enough to export in a single request."""

    key: str
    collection: str | None = None
    year: int | None = None
    # True count from /api/search, so saturation is known before exporting.
    documents: int = 0

    def ui_state(self, spec: IndexSpec) -> dict[str, Any]:
        state: dict[str, Any] = {}
        if self.collection is not None and spec.collection_attribute:
            state["refinementList"] = {spec.collection_attribute: [self.collection]}
        if self.year is not None:
            state["range"] = {YEAR_ATTRIBUTE: {"min": self.year, "max": self.year}}
        return state

    def search_params(self, spec: IndexSpec) -> dict[str, Any]:
        params: dict[str, Any] = {"hitsPerPage": 0}
        if self.collection is not None and spec.collection_attribute:
            params["facetFilters"] = [[f"{spec.collection_attribute}:{self.collection}"]]
        if self.year is not None:
            params["numericFilters"] = [f"{YEAR_ATTRIBUTE}={self.year}"]
        return params


@dataclass
class Shortfall:
    """A cell that exceeds the ceiling at the finest split the service allows."""

    collection: str | None
    year: int | None
    documents: int
    reachable: int
    reason: str


@dataclass
class Progress:
    done: set[str] = field(default_factory=set)
    shortfalls: list[Shortfall] = field(default_factory=list)
    documents_written: int = 0
    http_requests: int = 0


class Sisaltohaku:
    """Thin client over the two public endpoints, with retry and rate limiting."""

    def __init__(self, base_url: str = BASE_URL, *, timeout: float = 120.0, sleep: float = 0.0, retries: int = 4) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._sleep = sleep
        self._retries = retries
        self.requests = 0

    def _post(self, path: str, payload: Any) -> Any:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._base + path,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    self.requests += 1
                    if self._sleep:
                        time.sleep(self._sleep)
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                # Exponential backoff: the service is a demo instance and a
                # 7,000-request run should back off rather than hammer it.
                delay = 2**attempt
                logger.warning("%s failed (%s); retrying in %ds", path, exc, delay)
                time.sleep(delay)
        raise RuntimeError(f"{path} failed after {self._retries} attempts") from last

    def count(self, index: str, params: dict[str, Any] | None = None) -> int:
        """True, uncapped document count for a filter."""
        request = {"indexName": index, "params": {"hitsPerPage": 0, **(params or {})}}
        return int(self._post(SEARCH_ENDPOINT, [request])["results"][0]["nbHits"])

    def facet_values(self, index: str, attribute: str, *, limit: int = 1000) -> dict[str, int]:
        """Facet values and their counts, e.g. every collection in a corpus."""
        request = {
            "indexName": index,
            "params": {"hitsPerPage": 0, "facets": [attribute], "maxValuesPerFacet": limit},
        }
        facets = self._post(SEARCH_ENDPOINT, [request])["results"][0].get("facets") or {}
        return facets.get(attribute, {})

    def export(self, index: str, ui_state: dict[str, Any], *, max_results: int = EXPORT_CEILING) -> list[dict[str, Any]]:
        payload = {"index": index, "uiState": ui_state, "maxResults": max_results}
        return self._post(EXPORT_ENDPOINT, payload).get("hits") or []


def plan_slices(client: Sisaltohaku, spec: IndexSpec) -> tuple[list[Slice], list[Shortfall], int]:
    """Work out the coarsest set of slices that each fit under the ceiling.

    Returns the slices, the cells that cannot be made to fit, and the corpus total.
    Counting is done up front so the export phase is a straight walk with no
    surprises — and so an interrupted run resumes against a stable plan.
    """
    total = client.count(spec.name)
    logger.info("%s: %d documents in the live index", spec.name, total)

    if total <= EXPORT_CEILING:
        return [Slice(key="all", documents=total)], [], total

    slices: list[Slice] = []
    shortfalls: list[Shortfall] = []

    years = client.facet_values(spec.name, YEAR_ATTRIBUTE, limit=5000)
    logger.info("%s: %d distinct start years", spec.name, len(years))

    for year_label, year_count in sorted(years.items(), key=lambda kv: kv[0]):
        try:
            year = int(year_label)
        except ValueError:
            logger.warning("%s: skipping non-numeric year facet %r", spec.name, year_label)
            continue

        if year_count <= EXPORT_CEILING:
            slices.append(Slice(key=f"y={year}", year=year, documents=year_count))
            continue

        if not spec.collection_attribute:
            shortfalls.append(Shortfall(None, year, year_count, EXPORT_CEILING, "year exceeds the 10k ceiling and this corpus has no collection facet to subdivide by"))
            slices.append(Slice(key=f"y={year}", year=year, documents=EXPORT_CEILING))
            continue

        # The year is too big on its own, so split it by collection.
        collections = client.facet_values(spec.name, spec.collection_attribute, limit=1000)
        for collection in sorted(collections):
            cell = Slice(key=f"c={collection}|y={year}", collection=collection, year=year)
            cell.documents = client.count(spec.name, cell.search_params(spec))
            if cell.documents == 0:
                continue
            if cell.documents > EXPORT_CEILING:
                shortfalls.append(Shortfall(collection, year, cell.documents, EXPORT_CEILING, "single cell exceeds the 10k ceiling and cannot be subdivided further"))
                cell.documents = EXPORT_CEILING
            slices.append(cell)

    return slices, shortfalls, total


def _read_progress(corpus_dir: Path) -> Progress:
    checkpoint = corpus_dir / "checkpoint.json"
    if not checkpoint.exists():
        return Progress()
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    return Progress(done=set(data.get("done", [])))


def _write_checkpoint(corpus_dir: Path, progress: Progress) -> None:
    payload = {
        "done": sorted(progress.done),
        "shortfalls": [vars(s) for s in progress.shortfalls],
    }
    (corpus_dir / "checkpoint.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def harvest_index(client: Sisaltohaku, spec: IndexSpec, output: Path, *, resume: bool) -> dict[str, Any]:
    """Harvest one corpus, returning its report."""
    corpus_dir = output / spec.name
    corpus_dir.mkdir(parents=True, exist_ok=True)
    jsonl = corpus_dir / f"{spec.name}.jsonl.gz"

    progress = _read_progress(corpus_dir) if resume else Progress()
    if not resume and jsonl.exists():
        jsonl.unlink()

    started = time.perf_counter()
    slices, shortfalls, total = plan_slices(client, spec)
    progress.shortfalls = shortfalls

    pending = [s for s in slices if s.key not in progress.done]
    logger.info("%s: %d slices, %d already done, %d to fetch", spec.name, len(slices), len(slices) - len(pending), len(pending))

    if resume and jsonl.exists():
        progress.documents_written = sum(1 for _ in _iter_jsonl(jsonl))

    for n, slice_ in enumerate(pending, start=1):
        hits = client.export(spec.name, slice_.ui_state(spec), max_results=EXPORT_CEILING)
        # One gzip member per slice: gzip.open reads concatenated members
        # transparently, so appending is safe and the file stays a single valid
        # .jsonl.gz. Flushed before the checkpoint so a crash loses at most the
        # record that a slice was done, never the documents themselves.
        with gzip.open(jsonl, "ab") as handle:
            for hit in hits:
                handle.write((json.dumps(hit, ensure_ascii=False) + "\n").encode("utf-8"))
        progress.documents_written += len(hits)
        progress.done.add(slice_.key)
        _write_checkpoint(corpus_dir, progress)

        if n % 25 == 0 or n == len(pending):
            logger.info("%s: %d/%d slices, %d documents", spec.name, n, len(pending), progress.documents_written)

    unreachable = sum(s.documents - s.reachable for s in progress.shortfalls)
    elapsed = time.perf_counter() - started
    report = {
        "index": spec.name,
        "mode": "proxy",
        "complete": not progress.shortfalls,
        "index_total": total,
        "documents_written": progress.documents_written,
        "documents_unreachable": unreachable,
        "slices_remaining": 0,
        "coverage_pct": round(100.0 * progress.documents_written / total, 2) if total else 100.0,
        "http_requests": client.requests,
        "elapsed_seconds": round(elapsed, 1),
        "shortfalls": [vars(s) for s in progress.shortfalls],
    }
    (corpus_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def _iter_jsonl(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield line


def verify(output: Path, index: str) -> int:
    """Check a harvested corpus reads back cleanly and its objectIDs are unique.

    Worth running after a resumed harvest: the one failure mode resuming can
    introduce is a duplicated slice, and duplicate objectIDs are how it shows.
    """
    jsonl = output / index / f"{index}.jsonl.gz"
    if not jsonl.exists():
        logger.error("%s: nothing harvested at %s", index, jsonl)
        return 1

    seen: set[str] = set()
    duplicates = malformed = lines = 0
    for line in _iter_jsonl(jsonl):
        lines += 1
        try:
            record = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        object_id = record.get("objectID")
        if object_id in seen:
            duplicates += 1
        else:
            seen.add(object_id)

    logger.info("%s: %d lines, %d unique objectIDs, %d duplicates, %d malformed", index, lines, len(seen), duplicates, malformed)
    return 0 if not duplicates and not malformed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", default="all", choices=[*INDEXES, "all"], help="Corpus to harvest (default: all)")
    parser.add_argument("--output", type=Path, default=Path(".data"), help="Destination directory (default: .data)")
    parser.add_argument("--resume", action="store_true", help="Skip slices already recorded in checkpoint.json")
    parser.add_argument("--verify", action="store_true", help="Verify an existing harvest instead of fetching")
    parser.add_argument("--base-url", default=BASE_URL, help=f"Service base URL (default: {BASE_URL})")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to pause between requests, to be polite to a demo service")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    names = list(INDEXES) if args.index == "all" else [args.index]

    if args.verify:
        return max(verify(args.output, name) for name in names)

    client = Sisaltohaku(args.base_url, timeout=args.timeout, sleep=args.sleep)
    for name in names:
        report = harvest_index(client, INDEXES[name], args.output, resume=args.resume)
        logger.info(
            "%s: %d/%d documents (%.2f%%), %d unreachable, %d shortfall cells",
            name,
            report["documents_written"],
            report["index_total"],
            report["coverage_pct"],
            report["documents_unreachable"],
            len(report["shortfalls"]),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
