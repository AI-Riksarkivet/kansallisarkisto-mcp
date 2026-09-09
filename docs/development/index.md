---
icon: lucide/hammer
---

# Setup

## Repo layout

```
kansallisarkisto-mcp/
├── .data/                        # harvested corpora (git-ignored, 6.3 GB)
├── data/                         # built LanceDB tables (git-ignored)
├── packages/
│   ├── kansallisarkisto-lib/     # LanceDB spine, record model, ingest, search
│   └── kansallisarkisto-mcp/     # FastMCP tools, formatter, settings, entry point
├── .dagger/                      # Go Dagger module (package main, receiver KansallisarkistoMcp)
├── .docker/                      # kansallisarkisto-mcp.dockerfile + docker-compose.yml
├── docs/                         # this zensical site's markdown sources
├── scripts/                      # harvest.py, ingest_df.py, mcp_smoke.py
├── Makefile                      # thin wrappers over uv / dagger
├── pyproject.toml                # workspace root: [tool.uv.workspace], no [project] version
└── zensical.toml                 # site config (nav, theme)
```

A `uv` workspace of two packages (`[tool.uv.workspace] members = ["packages/*"]`):
`kansallisarkisto-lib` has no MCP dependency; `kansallisarkisto-mcp` depends on it via
`[tool.uv.sources]`. The root `pyproject.toml` carries no `[project]` section or version of
its own — each package's version lives in its own `pyproject.toml`.

## Makefile targets

| Target | Runs | Does |
|---|---|---|
| `install` | `uv sync --all-packages` | Install all workspace packages + the dev dependency group. |
| `ingest-df` | `uv run python scripts/ingest_df.py` | Build the `df` LanceDB table from `.data/df/df.jsonl.gz`. |
| `serve` | `uv run kansallisarkisto-mcp` | Run the MCP server over stdio. |
| `serve-http` | `KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp` | Run over streamable HTTP on `:8000`. |
| `inspect` | `npx @modelcontextprotocol/inspector uv run kansallisarkisto-mcp` | Open MCP Inspector against the stdio server. |
| `format` | `uv run ruff format .` | Format code. |
| `lint` | `uv run ruff check --fix .` | Lint and auto-fix. |
| `typecheck` | `uvx ty check` | Type check. |
| `check` | `format`, `lint`, `typecheck` | Composite: all three local code-quality checks. |
| `test` | `uv run pytest` | Run the test suite directly against the local venv. |
| `test-mcp` | `dagger call test-mcp` | End-to-end: production image + fixture table + real MCP client. |
| `ci` | `dagger call checks`, `dagger call test`, `dagger call test-mcp` | Full CI pipeline via Dagger, containerised — the same three calls `.github/workflows/ci.yml` makes. |
| `serve-image` | `dagger call serve-up --port 8000 up --ports 8000:8000` | Run the production image on the Dagger engine, with the test fixture already ingested, exposed on the host. |
| `clean` | | Remove `__pycache__`, `.ruff_cache`, `dist/`, `build/`, `*.egg-info`. |

## Tests

```bash
uv run pytest
```

Runs against the local venv, needs no network, and — importantly — **needs no corpus**.
`packages/kansallisarkisto-lib/tests/fixtures/df_sample.jsonl` holds 18 real charters chosen
to cover the corpus's documented traps: untranscribed records, unknown years, unlocated
places, open and closed dating intervals, and all four main languages. The whole suite ingests
that fixture into a temporary LanceDB and searches it for real, so the ingest, the index
configuration and the search are all exercised rather than mocked.

`asyncio_mode = "auto"` is set in the root `pyproject.toml`, so `async def test_*` functions
need no decorator.

## Dagger

The `.dagger/` module (`dagger/kansallisarkisto-mcp`, receiver `KansallisarkistoMcp`) drives
checks, tests, builds, local serving and releases identically on a laptop and in CI. List
every function with `dagger functions`.

- **`dagger call checks`** — `ruff format`, `ruff check --fix`, then verifies both plus
  `ty check` pass, then `pip-audit --strict --desc` as a dependency-vulnerability gate. See
  [Security](security.md).
- **`dagger call test`** — a fresh `python:3.14-slim` container running `pytest --tb=short -q`,
  independent of the local venv.
- **`dagger call test-server`** — builds the production image, starts it as a service and
  curls `/health`, which must answer 200.
- **`dagger call test-mcp`** (`make test-mcp`) — the deep end-to-end check. It ingests the
  test fixture into a LanceDB directory, mounts that at `/data` in the production image, and
  drives the running server with a real `fastmcp` client (`scripts/mcp_smoke.py`):
  `tools/list`, four `df_search` calls and a `df_get_charter` call, asserting on the formatted
  output. This is the only place the **index configuration** is verified end to end — Swedish
  stemming and accent folding are index-time settings, so a wrong FTS config is invisible to
  anything that searches only exact forms.
- **`dagger call serve-up --port 8000 up`** — the image, with the fixture table already
  ingested, exposed on the host for manual poking.

`make ci` runs exactly what `.github/workflows/ci.yml` runs — `checks`, `test` and `test-mcp` —
so running it before pushing catches the same failures CI would.

### Three choices worth knowing about

**Every `source` parameter carries an `+ignore`.** Dagger uploads the host directory into
the engine before any function runs, and `.dockerignore` does not apply to that — it only
filters the Dockerfile build that happens later. With a 6.3 GB `.data/` and a 483 MB
`.venv/` in the repo root, an unfiltered `+defaultPath="/"` would ship 6.7 GB to the engine
on every single call. The `+ignore` list mirrors `.dockerignore` and is the Dagger-native
way to say it.

**`dagger.json` pins `engineVersion` to the version the module is verified against.**
`engineVersion` is a *minimum*, so a lower pin constrains nothing
— CI runs `version: "latest"` either way — while a pin above the locally installed CLI stops
`make ci` from running at all until the developer upgrades. Raise it when the module starts
depending on something newer, not before.

**There are no `compose-up` / `compose-test` Dagger functions.** This service is defined by a
data mount, and a host bind mount is exactly what Dagger's daemon-less compose module cannot express — it fails
resolving the bind source before the service ever starts. Rather than ship two Make targets
that can never pass, `.docker/docker-compose.yml` is left to real `docker compose` (where it
is verified to build, mount `../data` and serve), and `dagger call serve-up` covers the
"run the image without a local daemon" case — better, since it ingests the fixture so there
is something to search. Dropping it also removed the module's only third-party dependency,
which is why `dagger develop` now needs no network at all.
