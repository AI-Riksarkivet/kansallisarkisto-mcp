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

[![Tests](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/ci.yml)
[![Security](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/security.yml)
[![Documentation](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/docs.yml/badge.svg)](https://ai-riksarkivet.github.io/kansallisarkisto-mcp/)
[![Secret Leaks](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/trufflehog.yml/badge.svg)](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/actions/workflows/trufflehog.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](.python-version)
[![License Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Data: Kansallisarkisto](https://img.shields.io/badge/data-Kansallisarkisto-8A2BE2.svg)](https://sisaltohaku.demo.kansallisarkisto.fi/)

[![SLSA Level 3](https://img.shields.io/badge/SLSA-Level%203-blue.svg)](docs/development/security.md#slsa-build-level-3-provenance)
[![Signed with Sigstore](https://img.shields.io/badge/Sigstore-signed-purple.svg)](docs/development/security.md#supply-chain-attestations-at-publish-time)
[![SBOM SPDX + CycloneDX](https://img.shields.io/badge/SBOM-SPDX%20%2B%20CycloneDX-green.svg)](docs/development/security.md#sbom-generation)

The three supply-chain badges describe the release pipeline in
[`publish.yml`](.github/workflows/publish.yml), and each links to the section of the security
docs that says how it is produced. Nothing has been released yet — there are no tags — so
they are a statement about how this project releases, not yet about artefacts you can
download and verify.

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

- `df_search(keyword, offset=0, limit=25, language?, issuingplace?, country?, year_min?, year_max?, match_all=true)`
  — full-text search over the charters. Swedish stemming and accent folding are applied, so
  `konungen` matches `konung` and `Abo` matches `Åbo`. Several words must **all** appear
  (`match_all=false` matches any of them) and `"quoted words"` are an exact phrase; `AND`, `OR`
  and `NOT` are not operators and are matched as ordinary words. Each hit leads with its
  **DF number**, the citable identifier. Page with `offset`.
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
| `KA_MCP_OTEL_ENABLED` | `false` | Master switch for OpenTelemetry. Off means the instrumentation resolves to no-ops and no collector is contacted. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector endpoint. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf`. |
| `OTEL_SERVICE_NAME` | `kansallisarkisto-mcp` | Service name on the exported resource. |
| `KA_MCP_OTEL_LOG_BRIDGE` | `true` | Bridge Python logging to OTel logs (only when telemetry is on). |
| `KA_MCP_OTEL_ENABLED` | `false` | Master switch for OpenTelemetry. Unset, the SDK is never initialised and every instrumentation call resolves to a no-op — which is what a stdio client on a laptop should get. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector endpoint. Only read when telemetry is enabled. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf`. |
| `OTEL_SERVICE_NAME` | `kansallisarkisto-mcp` | Service name reported to the collector. |
| `KA_MCP_OTEL_LOG_BRIDGE` | `true` | Bridge Python logging into OpenTelemetry logs. |

Read from the environment or a `.env` file in the working directory. The `OTEL_*` variables
are the SDK's own, so anything else it recognises works too.

## Architecture

```
MCP client ──/mcp──▶ ra_mcp_kansallisarkisto_mcp (FastMCP tools + formatter + settings)
                        └─▶ ra_mcp_kansallisarkisto_lib (LanceDB spine + ingest + search)
                               └─▶ data/df (LanceDB table, built from the harvested export)
```

A uv workspace of two packages:

- `packages/kansallisarkisto-lib` — the LanceDB spine (`dataset.py`), the record model,
  ingest, and search operations. No MCP dependency, so it is usable on its own.
- `packages/kansallisarkisto-mcp` — FastMCP tools, LLM-facing descriptions, env settings,
  server entry point.

## The data

The corpora come from **[Sisältöhaku](https://sisaltohaku.demo.kansallisarkisto.fi/)**, the
content-search demo service of **[Kansallisarkisto — the National Archives of
Finland](https://kansallisarkisto.fi/)**. `scripts/harvest.py` (`make harvest`) downloads
them through the service's own public JSON endpoints, the same ones the site's "download
results" button uses.

Coverage is 98.25% of the live index. The shortfall is systematic rather than sampling:
Elasticsearch enforces a 10,000-document `from + size` ceiling per query and the public
frontend exposes only two filterable axes, so a handful of large facet cells cannot be
subdivided far enough to fit. The harvester records those as shortfalls instead of quietly
returning a short file. See [`docs/how-it-works/data-sources.md`](docs/how-it-works/data-sources.md)
for the corpus reference and the traps that shape this server's schema.

A harvest is a **snapshot**, and the live index moves — `voudintilit` grew from 99,031 to
99,125 documents between two harvests. The live service is always the authority.

## Credit and licence

The records are the property of **Kansallisarkisto** and were published through its
[Sisältöhaku demo service](https://sisaltohaku.demo.kansallisarkisto.fi/). This repository
holds no records — only the code that downloads, indexes and searches them.

Cite **the archive**, not this snapshot, as the source of any document, and consult
Kansallisarkisto for terms of reuse and redistribution. Anything quoted from these corpora is
machine-recognised text and should be checked against the archive's own page images.

The code in this repository is Apache-2.0.

## Development

```bash
make check     # ruff format + lint + ty
make test      # pytest — no network, no corpus needed
make test-mcp  # end-to-end: production image + fixture table + real MCP client (Dagger)
make ci        # the full pipeline GitHub Actions runs
```

`packages/kansallisarkisto-lib/tests/fixtures/df_sample.jsonl` holds 18 real charters chosen
to cover the corpus's documented traps — untranscribed records, unknown years, unlocated
places, open and closed dating intervals, all four main languages — so the whole suite runs
without the 6.3 GB export.
