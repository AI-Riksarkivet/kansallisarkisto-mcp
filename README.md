---
title: kansallisarkisto-mcp
emoji: 📜
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
---

# kansallisarkisto-mcp

MCP server over the **Sisältöhaku** corpora of Kansallisarkisto, the National Archives of
Finland — full-text search across machine-transcribed archival text, served from LanceDB.

Currently serving **Diplomatarium Fennicum** (`df`): 6,876 medieval charters, letters and
account entries concerning Finland, 859–1530. The two larger corpora — `voudintilit`
(98,945 bailiff accounts, 1539–1634) and `tuomiokirjat` (7,835,557 court-record pages,
1600s–1900s) — are harvested and documented but not yet ingested.

## The text is not in Finnish

Finland was part of the Swedish realm until 1809, and these records were kept in the
administrative language of the day. The documents are **early-modern Swedish, Latin and
German**; only the catalogue metadata — index terms, language and country labels — is
Finnish. Search accordingly: `bref` not `brev`, `konung` not `kung`, `Åbo` not `Turku`,
`Viborg` not `Viipuri`.

## Tools

- `df_search(keyword, offset=0, limit=25, language?, issuingplace?, country?, year_min?, year_max?)`
  — full-text search over the charters. Swedish stemming and accent folding are applied, so
  `konungen` matches `konung` and `Abo` matches `Åbo`. Each hit leads with its **DF number**,
  the citable identifier. Page with `offset`.
- `df_get_charter(df_number)` — one charter's full transcript and catalogue record.

## Run locally

The corpora are not in this repository (6.3 GB; `.data/` is git-ignored) — re-download them
from the live service first:

```bash
make install
make harvest                              # or: uv run python scripts/harvest.py --index all
make ingest-df                            # .data/df/df.jsonl.gz -> data/df (LanceDB)
uv run kansallisarkisto-mcp               # stdio, for MCP clients
KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp   # streamable HTTP on :8000 (/mcp)
```

Or containerised. The image ships **without data** — mount a LanceDB directory at `/data`:

```bash
docker compose -f .docker/docker-compose.yml up --build   # mounts ./data read-only
```

or by hand:

```bash
docker build -f .docker/kansallisarkisto-mcp.dockerfile -t kansallisarkisto-mcp .
docker run -p 8000:8000 -v "$PWD/data:/data:ro" kansallisarkisto-mcp
```

Bind-mount it rather than copying it in: lance writes mode-`0600` files, so a table copied
into an image without `--chown=1000:1000` is unreadable by the non-root runtime user — and
lance reports that as `Not found`. The server checks for this at boot and says so.

Without a table the server still boots; every tool call returns a clear missing-table
message rather than crashing, and the boot log names the tables it did find.

## Settings

| variable | default | meaning |
|---|---|---|
| `KA_LANCEDB_URI` | *(resolved)* | Where the LanceDB tables live. Unset resolves to `<project root>/data` in a clone, `/data` in the image. Any lancedb URI works, including `s3://`. |
| `KA_MCP_TRANSPORT` | `stdio` | `stdio` or `http`. |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | HTTP bind address. |
| `LOG_LEVEL` | `INFO` | Root log level; logs go to stderr so stdio transport stays clean. |

## Architecture

```
MCP client ──/mcp──▶ ra_mcp_kansallisarkisto_mcp (FastMCP tools + formatter + settings)
                        └─▶ ra_mcp_kansallisarkisto_lib (LanceDB spine + ingest + search)
                               └─▶ data/df (LanceDB table, built from the harvested export)
```

- `packages/kansallisarkisto-lib` — the LanceDB spine (`dataset.py`), the record model,
  ingest, and search operations. No MCP dependency.
- `packages/kansallisarkisto-mcp` — FastMCP tools, LLM-facing descriptions, env settings,
  server entry point.

The layout follows [ape-mcp](https://github.com/carpelan/ape-mcp) — uv workspace, two-package
`<domain>-lib` / `<domain>-mcp` split, Dagger CI, digest-pinned base image — and the LanceDB
spine follows [ra-mcp](https://github.com/AI-Riksarkivet/ra-mcp)'s `ra_mcp_dataset_lib`, minus
its OpenTelemetry layer. Both packages are shaped as an `ra_mcp_*_lib` / `ra_mcp_*_mcp` module
pair so they can merge into ra-mcp as a module later with no rework.

## The data

Harvested 29 July 2026 from `sisaltohaku.demo.kansallisarkisto.fi` via its public
`/api/export-all` endpoint, as gzipped JSON Lines under `.data/`. Coverage is 98.25% of the
live index; the shortfall is a systematic consequence of Elasticsearch's 10,000-document
`from + size` ceiling, not sampling. See [`docs/how-it-works/data-sources.md`](docs/how-it-works/data-sources.md)
for the corpus reference, and the traps that shape this server's schema.

The records are the property of Kansallisarkisto and were published through its Sisältöhaku
demo service. This is a derived snapshot; the live service is the authority. Cite the
archive, not this snapshot.

## Development

```bash
make check     # ruff format + lint + ty
make test      # pytest — no network, no corpus needed
make test-mcp  # end-to-end: production image + fixture table + real MCP client (Dagger)
make ci        # the full pipeline GitHub Actions runs
```

`packages/kansallisarkisto-lib/tests/fixtures/df_sample.jsonl` holds 16 real charters chosen
to cover the corpus's documented traps — untranscribed records, unknown years, unlocated
places, open and closed dating intervals, all four main languages — so the whole suite runs
without the 6.3 GB export.
