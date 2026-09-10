# voudintilit Implementation Plan

> Executed in the session that wrote it, task by task, test-first. Design:
> [2026-09-10-voudintilit-design.md](2026-09-10-voudintilit-design.md).

**Goal:** serve `voudintilit` (98,945 bailiff-account pages) beside `df`, with page-level Astia
links and archival references, then measure `tuomiokirjat`.

**Architecture:** a second LanceDB table in the same database, a per-corpus record model,
ingest, search facade, formatter and tool module, all on the shared `dataset.py` spine. Astia
metadata is fetched once into a harvest-time snapshot and joined at ingest.

**Tech stack:** Python 3.14, uv workspace, LanceDB FTS, FastMCP, pytest, Dagger.

Nothing is committed until the user approves; each task ends green, not with a commit.

---

### Task 1 — Astia snapshot

- Create `packages/kansallisarkisto-lib/src/ra_mcp_kansallisarkisto_lib/astia.py`:
  `parse_files`, `parse_metadata`, `volume_entry`, `page_url`, `load_snapshot`.
- Test: `packages/kansallisarkisto-lib/tests/test_astia.py` (payloads trimmed from the live
  responses for volume 1578628789).
- Create `scripts/fetch_astia.py` — resumable, polite (sleep between requests), failures
  reported rather than written. Run it: `uv run python scripts/fetch_astia.py` →
  `.data/voudintilit/astia.jsonl`.

### Task 2 — Fixture

- `packages/kansallisarkisto-lib/tests/fixtures/voudintilit_sample.jsonl` and
  `voudintilit_astia_sample.jsonl`: real pages covering both collections, a volume with a
  page gap, the inverted-year volume, the catalogue volume, an empty page.

### Task 3 — Model

- `VoudintilitRecord.from_json(row, astia_volume)` in `models.py`. Tests: page number from
  `file_id`, `0` years → null, inverted pair keeps the start year, Astia join (reference,
  title fallback, url), no Astia entry → no url, `searchable_text`.

### Task 4 — Ingest

- `VOUDINTILIT_TABLE` in `config.py`; `VOUDINTILIT_SCHEMA` and `ingest_voudintilit` in
  `ingest.py`; `scripts/ingest_voudintilit.py`; `make ingest-voudintilit`. Tests: row count,
  indexes searchable, empty export raises.

### Task 5 — Search

- `VoudintilitSearch.search` (collection / account_book / year filters) and `.get_page`
  (with previous/next existing page) in `search_operations.py`. Tests per filter, gaps,
  unknown id.

### Task 6 — Tools and formatter

- `voudintilit_tool.py`, formatter functions. Tests: validation, missing table, citation
  line, link, empty page, newline injection.

### Task 7 — Server

- `tools.py`: a lazy facade per table; `readiness` over every table; per-table boot check in
  `server.py`; instructions; landing page lists the new tools (`test_routes` enforces it).

### Task 8 — Quality

- Retrieval-quality tests on the fixture; findability sweep over the real table; extend
  `scripts/mcp_smoke.py`; `dagger call test-mcp`.

### Task 9 — Docs

- README, `docs/tools/voudintilit-*.md` + nav, `data-sources.md`, search tips, landing page.

### Task 10 — Real data and release (ask first)

- Full ingest, local container test, bucket sync, release v0.2.0, bump `.docker/hf.dockerfile`,
  redeploy the Space, smoke-test it.

### Task 11 — tuomiokirjat measurement

- Full trial ingest; record table and index size, build time, peak memory, and query latency
  under `--cpus=2 --memory=16g`.
