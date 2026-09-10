<div align="center">
  <img src="https://raw.githubusercontent.com/AI-Riksarkivet/kansallisarkisto-mcp/main/docs/assets/logo-ka-bg.png" alt="kansallisarkisto-mcp logo" width="350">
</div>


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

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/AI-Riksarkivet/kansallisarkisto-mcp/badge)](https://scorecard.dev/viewer/?uri=github.com/AI-Riksarkivet/kansallisarkisto-mcp)
[![SLSA Level 3](https://img.shields.io/badge/SLSA-Level%203-blue.svg)](docs/development/security.md#slsa-build-level-3-provenance)
[![Signed with Sigstore](https://img.shields.io/badge/Sigstore-signed-purple.svg)](docs/development/security.md#supply-chain-attestations-at-publish-time)
[![SBOM SPDX + CycloneDX](https://img.shields.io/badge/SBOM-SPDX%20%2B%20CycloneDX-green.svg)](docs/development/security.md#sbom-generation)

MCP server over the **Sisältöhaku** corpora of Kansallisarkisto, the National Archives of
Finland — full-text search across machine-transcribed archival text, served from LanceDB.

Three corpora: **Diplomatarium Fennicum** (`df`), 6,876 medieval charters, letters and
account entries concerning Finland, 859–1530; **`voudintilit`**, 98,945 pages of the Swedish
crown's bailiff accounts for Häme and Satakunta, 1539–1635; and **`tuomiokirjat`**, 7.8
million pages of Finnish lower-court records from 223 archives, 1610–1931. The pages of the
two paged corpora are cited by their archival reference and linked to their image in Astia,
Kansallisarkisto's digital archive — every voudintilit page, and 99% of the court records
(240 volumes carry no signum in Astia; 0.05% of pages have no image link).

The range is wide but the weight is late: 83% of `df` falls in 1400–1530 and barely 240
charters predate 1300, so a thin result for an early century is the archive rather than the
query.

## Quick start

The server is hosted on Hugging Face, so the quickest start is to connect to it:

```bash
claude mcp add --transport http kansallisarkisto https://riksarkivet-kansallisarkisto-mcp.hf.space/mcp
```

For claude.ai, add a custom connector with the same URL.

Running it yourself is cheap too — harvesting `df` takes about three seconds, two HTTP
requests, 3 MB:

```bash
make install
make harvest       # df only: 6,876 charters, ~3 s, 100% of the live index
make ingest-df     # .data/df/df.jsonl.gz -> data/df (LanceDB, ~69 MB)

claude mcp add kansallisarkisto -- uv run kansallisarkisto-mcp
```

Run that from the repository root, or add `--cwd /path/to/kansallisarkisto-mcp`, so the
server resolves `data/` next to the project. For Claude Desktop, Cursor or Windsurf, add a
stdio server invoking `uv run kansallisarkisto-mcp` with the repo as its working directory.
The larger corpora are a different proposition — see [Run locally](#run-locally).

## What a result looks like

```text
> df_search(keyword="konung", issuingplace="Åbo", limit=2)

Diplomatarium Fennicum search results for 'konung': showing 2 of 49 records (offset 0)

**DF 2457** — 1442 — Åbo, Suomi
  language: ruotsi · index term: Paikallishallinto, Asiakirjat
  Jagh Carll Knutson, riddare, kännes och giör witterligit medh thette mit öpne breff, adt
  iagh hafwer vndt bårgarne i Raumo på min nådhige herre konung Christoffers wegne, adt the
  skulle och måghe bruka theras köpslaghan i alle måttho som the bårgare göra i Åbo …
```

Karl Knutsson, 1442, granting the burghers of Rauma the trading rights of Åbo. Read it in
full with `df_get_charter(df_number=2457)`, and cite it as **DF 2457** —
<https://df.kansallisarkisto.fi/document/2457>.

## The text is not in Finnish

Finland was part of the Swedish realm until 1809, and these records were kept in the
administrative language of the day. The documents are **early-modern Swedish, Latin and
German**; only the catalogue metadata — index terms, language and country labels — is
Finnish. Search accordingly: `bref` not `brev`, `konung` not `kung`, `Åbo` not `Turku`,
`Viborg` not `Viipuri`.

That rule governs the **text**. The `issuingplace` **filter** is a cataloguer's vocabulary of
499 values, and it is mixed: Finnish and Swedish places keep their historical Swedish form
(`Åbo`, `Viborg`, `Nådendal`), but places outside that realm are recorded under their modern
name — `Tallinn` not `Reval`, `Gdansk` not `Danzig`, `Tartu` not `Dorpat`. The historical
forms of those three match nothing at all. And it is the place of *issue*: a third of the
corpus records none, so a charter *about* Tallinn is found by searching the text for the
period name — `reval*|reual*|revel*|reuel*|reffl*` — not by the filter.

## Tools

- `df_search(keyword, offset=0, limit=25, language?, issuingplace?, country?, year_min?, year_max?, match_all=true, fuzzy=0)`
  — full-text search over the charters. Swedish stemming and accent folding are applied, so
  `konungen` matches `konung` and `Abo` matches `Åbo`. Several words must **all** appear
  (`match_all=false` matches any of them) and `"quoted words"` are an exact phrase; a trailing
  `*` is a prefix (`lepros*` — Latin and German are not stemmed) and `|` lists alternatives
  (`bref|breff`). `AND`, `OR` and `NOT` are not operators and are matched as ordinary words.
  Spelling was never standardised, so `fuzzy=1` is the right second attempt when a result set
  looks thin — pass a base form, since a fuzzy term skips stemming. Each hit leads with its
  **DF number**, the citable identifier. Page with `offset`.
- `df_get_charter(df_number)` — one charter's full transcript and catalogue record.

The catalogue's index term is a controlled vocabulary of 75 values shaped `Issuer,
DocumentType` — `Paikallishallinto` (local administration, 1,783), `Kaupungit` (towns, 1,171),
`Piispat` (bishops, 402); `Asiakirjat` (charters, 3,264), `Kirjeet` (letters, 2,215),
`Tili- ja pöytäkirjamerkinnät` (account entries, 1,007). It has no filter of its own, but it is
indexed, so those words work as keywords: `df_search(keyword="Piispat", issuingplace="Åbo")`.

Every DF number resolves to **`https://df.kansallisarkisto.fi/document/<number>`** — the
National Archives' own edition of that charter, with the printed-edition references (FMU, REA)
and any images. That is the link to give a reader; a DF number identifies the document as an
informational entity, not one particular edition, so it stays valid as editions change.

For `voudintilit`:

- `voudintilit_search(keyword, offset=0, limit=25, collection?, account_book?, year_min?, year_max?, match_all=true, fuzzy=0)`
  — full-text search over the bailiff-account pages, in early-modern Swedish. `collection` is
  `hame` or `satakunta`; `account_book` is a substring of the Finnish title (`Sääksmäen`,
  `Hämeen linnan`, `Maakirja`). `bref|breff` matches either spelling; a prefix `*` is not
  available here — the corpus is too large for a vocabulary — so list spellings or use
  `fuzzy=1`. Each hit is one page, led by its citation — reference number, account book, year
  and page, such as **2372 Ylä-Satakunnan tilikirja 1585, p. 16** — and linked to its image in
  Astia.
- `voudintilit_get_page(page_id)` — one page's full text, with the ids of the previous and next
  pages in its volume: accounts run across pages.

For `tuomiokirjat`:

- `tuomiokirjat_search(keyword, offset=0, limit=25, collection?, series?, year_min?, year_max?, match_all=true, fuzzy=0)`
  — full-text search over the court-record pages, in Swedish. `collection` is the archive and
  `series` the series, both substrings (`Turun raastuvanoikeuden`, `Varsinaisten asioiden`);
  common words match more than 10,000 pages — the result then says so and how to narrow. As
  for voudintilit, `|` works and a prefix `*` does not. Each hit is one page, led by its
  citation — series, signum, year and page, such as **Helsingin raastuvanoikeuden tuomiokirjat
  g:87 1792, p. 45** — with the archive beneath, and linked to its image.
- `tuomiokirjat_get_page(page_id)` — one page's full text, with the previous and next pages
  of its volume: a case runs across pages.

## Run locally

No corpus ships with this repository — `.data/` and `data/` are both git-ignored, and the
data is re-harvested rather than versioned. `make harvest` takes `df` alone, which is the
three-second path above. `voudintilit` harvests in about a minute, and its Astia snapshot —
the archival references and page links — takes about 35 minutes more:

```bash
uv run python scripts/harvest.py --index voudintilit
make fetch-astia          # ~3,200 requests to Astia, resumable
make ingest-voudintilit
```

`tuomiokirjat` is a different proposition: the harvest is about 1.5 hours and 6.3 GB, the
Astia snapshot 12,284 requests, and the ingest about 20 minutes with 7 GiB of memory for a
table of 21 GB:

```bash
uv run python scripts/harvest.py --index tuomiokirjat
make fetch-astia-tuomiokirjat
make ingest-tuomiokirjat
```

```bash
uv run python scripts/harvest.py --index all        # all three corpora (6.3 GB)
uv run kansallisarkisto-mcp                         # stdio, for MCP clients
KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp   # streamable HTTP on :8000 (/mcp)
```

Over HTTP the server also answers `/health` (liveness) and `/ready` (readiness — 503 until a
searchable table is mounted); see [Observability](docs/development/observability.md).

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
| `KA_MCP_STAGE_DATASETS` | `false` | Copy the tables onto local disk at boot and serve the copy. For a Hugging Face Space, whose bucket mount lance cannot query under load — see [Deployment](docs/development/deployment.md#hugging-face-space). |
| `KA_MCP_STAGE_DIR` | `/data-local` | Where that copy goes. Must be writable by the runtime user. |
| `KA_MCP_TRANSPORT` | `stdio` | `stdio` or `http`. |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | HTTP bind address. |
| `LOG_LEVEL` | `INFO` | Root log level; logs go to stderr so stdio transport stays clean. |
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

The three supply-chain badges above describe the release pipeline in
[`publish.yml`](.github/workflows/publish.yml), each linking to the section of the security
docs that says how it is produced. The first release,
[v0.1.0](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/releases/tag/v0.1.0), went
through all of it: the image `riksarkivet/kansallisarkisto-mcp` is signed, and its SBOMs and
provenance are attached to the release.

`packages/kansallisarkisto-lib/tests/fixtures/df_sample.jsonl` holds 18 real charters chosen
to cover the corpus's documented traps — untranscribed records, unknown years, unlocated
places, open and closed dating intervals, all four main languages — so the whole suite runs
without the 6.3 GB export.
