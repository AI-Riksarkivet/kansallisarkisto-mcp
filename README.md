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
Finland — full-text search across 7.8 million pages of machine-transcribed archival text,
served from LanceDB.

| corpus | what | pages | period | tools |
|---|---|---:|---|---|
| `df` | **Diplomatarium Fennicum** — the scholarly edition of the medieval charters, letters and account entries concerning Finland | 6,876 | 859–1530 | `df_search`, `df_get_charter` |
| `voudintilit` | the Swedish crown's **bailiff accounts** for the Häme and Satakunta bailiwicks: land registers and yearly account books, page by page | 98,945 | 1539–1635 | `voudintilit_search`, `voudintilit_get_page` |
| `tuomiokirjat` | the judgement books and minutes of Finland's **lower courts** — town, district, bailiffs', land-partition and appeal courts — from 223 archives, page by page | 7,742,958 | 1610–1931 | `tuomiokirjat_search`, `tuomiokirjat_get_page` |

Every charter is cited by its DF number and linked to the archive's own edition. Every page
of the two paged corpora is cited by its archival reference and linked to its image in
Astia, Kansallisarkisto's digital archive — all of voudintilit, and 99% of the court records
(240 volumes carry no signum in Astia; 0.05% of pages have no image link).

## Quick start

The server is hosted on Hugging Face, so the quickest start is to connect to it:

```bash
claude mcp add --transport http kansallisarkisto https://riksarkivet-kansallisarkisto-mcp.hf.space/mcp
```

For claude.ai, add a custom connector with the same URL. The Space sleeps after 48 hours
without traffic and takes about four minutes to come back — it copies 22 GB of tables onto
local disk first — so a client that times out once will usually connect on the second try.

Running it yourself with the charters is cheap — the harvest is two HTTP requests, 3 MB,
about three seconds:

```bash
make install
make harvest       # df only: 6,876 charters, ~3 s, 100% of the live index
make ingest-df     # .data/df/df.jsonl.gz -> data/df (LanceDB, ~69 MB)

claude mcp add kansallisarkisto -- uv run kansallisarkisto-mcp
```

Run that from the repository root, or add `--cwd /path/to/kansallisarkisto-mcp`, so the
server resolves `data/` next to the project. For Claude Desktop, Cursor or Windsurf, add a
stdio server invoking `uv run kansallisarkisto-mcp` with the repo as its working directory.
The two page corpora cost more to build — see [Run locally](#run-locally).

## What a result looks like

A charter:

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

A court-record page — narrowed to one town court and one decade, because `hustru` alone
matches more than 10,000 pages:

```text
> tuomiokirjat_search(keyword="hustru", series="Turun raastuvanoikeuden", year_min=1650, year_max=1660, limit=1)

Tuomiokirjat search results for 'hustru': showing 1 of 604 records (offset 0)

**Turun raastuvanoikeuden tuomiokirjat z:28 1659, p. 45**
  Raastuvanoikeuksien renovoidut tuomiokirjat · page g5r_IZcBCao99UPKnENq
  64. Confusion som Uthi branden skedde, förlagd bleef, hafwer således hängt här till; Men
  såsom nu befans af ran¬ sakningen, at för be:te S. Grels Bengtßons hustru … slagit Walborg
  Jacobsdotter en påst, och Rätten inthet annat till stodh än döma …
  https://astia.narc.fi/uusiastia/viewer/?fileId=5932813166&aineistoId=2329280746
```

The Turku town court in 1659, a wife accused of striking Walborg Jacobsdotter in the
courthouse porch. The bold line is the citation — series, the volume's signum, year, page —
and the link opens that page's image. `tuomiokirjat_get_page(page_id="g5r_IZcBCao99UPKnENq")`
gives the whole page and the ids of the pages either side of it, because a case runs across
pages. A bailiff-account hit has the same shape: **3853 Mustialan kartanon voutikunnan
tilikirja 1558, p. 53**, butter delivered to Stockholm castle's storehouse.

## The text is not in Finnish

Finland was part of the Swedish realm until 1809, and these records were kept in the
administrative language of the day — the courts wrote Swedish until the late 19th century.
The documents are **early-modern Swedish, Latin and German**; only the catalogue metadata —
index terms, archive and series names, language and country labels — is Finnish. Search
accordingly: `bref` not `brev`, `konung` not `kung`, `Åbo` not `Turku`, `Viborg` not
`Viipuri`.

That rule governs the **text**. The `issuingplace` **filter** on the charters is a cataloguer's
vocabulary of 499 values, and it is mixed: Finnish and Swedish places keep their historical
Swedish form (`Åbo`, `Viborg`, `Nådendal`), but places outside that realm are recorded under
their modern name — `Tallinn` not `Reval`, `Gdansk` not `Danzig`, `Tartu` not `Dorpat`. The
historical forms of those three match nothing at all. And it is the place of *issue*: a third
of the corpus records none, so a charter *about* Tallinn is found by searching the text for
the period name — `reval*|reual*|revel*|reuel*|reffl*` — not by the filter.

## Searching

The same query syntax on every corpus. Swedish stemming and accent folding are applied, so
`konungen` matches `konung` and `Abo` matches `Åbo`. Several words must **all** appear
(`match_all=false` matches any of them); `"quoted words"` are an exact phrase; `bref|breff`
matches either spelling. `AND`, `OR` and `NOT` are not operators and are matched as ordinary
words. Spelling was never standardised, so `fuzzy=1` is the right second attempt when a
result set looks thin — pass a base form, since a fuzzy term skips stemming.

On the charters a trailing `*` is a **prefix**: `lepros*` finds `leprosi`, `leprosorum` and
`leprosis`, which no stemmer here would — Latin and German are not stemmed. The two page
corpora are too large to hold the vocabulary a prefix expands against, so there `*` is
refused with a message saying so; list the spellings, or use `fuzzy=1`.

**Paging and totals.** `offset` and `limit` (default 25, at most 100) slice one ranked result
set, so page two continues page one without gaps or repeats, and the total is a true count of
matches — up to 10,000. Past that the total reads `10000+`, a floor: the ranking is over the
top 10,000 by relevance and paging cannot reach beyond them. Common Swedish words pass the
cap on the court records, and `smör` alone does on the accounts; the result then carries a
note saying so and naming the filters to narrow with. Narrowed, the total means something
again — `hustru` in the Turku town court of the 1650s is 604 pages.

## Tools

All six are read-only and reach no network. Errors are sentences, never exceptions: a blank
keyword, an inverted year range or a missing table each comes back as text the caller can act
on.

### `df` — Diplomatarium Fennicum

- `df_search(keyword, offset=0, limit=25, language?, issuingplace?, country?, year_min?, year_max?, match_all=true, fuzzy=0)`
  — full-text search over the charters, narrowable by language (an unaccented Finnish label:
  `ruotsi`, `latina`, `saksa`, `venaja`), place and country of issue (substrings), and year
  range. Each hit leads with its **DF number**, the citable identifier.
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

The range is wide but the weight is late: 83% of `df` falls in 1400–1530 and barely 240
charters predate 1300, so a thin result for an early century is the archive rather than the
query. 36% of the charters are catalogued but never transcribed; they are still returned —
findable by place, index term and language — and marked as untranscribed.

### `voudintilit` — bailiff accounts

- `voudintilit_search(keyword, offset=0, limit=25, collection?, account_book?, year_min?, year_max?, match_all=true, fuzzy=0)`
  — full-text search over the account-book pages. `collection` is `hame` or `satakunta`;
  `account_book` is a substring of the Finnish title (`Sääksmäen`, `Hämeen linnan`,
  `Maakirja` for the land registers). Each hit is one page, led by its citation — reference
  number, account book, year and page — and linked to its image in Astia.
- `voudintilit_get_page(page_id)` — one page's full text, with the ids of the previous and next
  pages in its volume: accounts run across pages.

A page id is `<volume>_<page>`, e.g. `1578628789_0016`. The export carries no reference and no
link; both come from Astia's own catalogue, fetched once per volume at harvest time.

### `tuomiokirjat` — court records

- `tuomiokirjat_search(keyword, offset=0, limit=25, collection?, series?, year_min?, year_max?, match_all=true, fuzzy=0)`
  — full-text search over the court-record pages. `collection` is the archive and `series`
  the series, both substrings: for the 17th–18th-century town courts the series names the
  court (`Turun raastuvanoikeuden`, `Porin`), for the 19th–20th-century district courts the
  record type — `Varsinaisten asioiden pöytäkirjat` (cases) or `Ilmoitusasioiden pöytäkirjat`
  (registrations: land transfers, mortgages, guardianships) — with the archive naming the
  district. Each hit is one page, led by its citation — series, signum, year and page — with
  the archive beneath, and linked to its image.
- `tuomiokirjat_get_page(page_id)` — one page's full text, with the previous and next pages
  of its volume: a case runs across pages.

A page id is the export's own document id, e.g. `Y4Q4IZcBCao99UPKS6L8`, because
`<volume>_<page>` is not unique here: Sisältöhaku holds 60,000 images twice or three times
under distinct ids, and the ingest keeps one of each. The corpus is uneven in time — the whole
17th century is 240,000 pages, the 1910s alone 1.1 million — so a thin result for an early
decade is the archive.

## Run locally

No corpus ships with this repository — `.data/` and `data/` are both git-ignored, and the
data is re-harvested rather than versioned. `make harvest` takes `df` alone, which is the
three-second path above. The page corpora need an Astia snapshot as well — the archival
references, and for voudintilit the page links — fetched once per volume:

```bash
uv run python scripts/harvest.py --index voudintilit   # ~1 min
make fetch-astia                                        # ~3,200 requests to Astia, ~35 min, resumable
make ingest-voudintilit                                 # ~10 s, 296 MB

uv run python scripts/harvest.py --index tuomiokirjat  # ~1.5 h, 6.3 GB
make fetch-astia-tuomiokirjat                           # 12,284 requests, ~1.5 h, resumable
make ingest-tuomiokirjat                                # ~20 min, ~7 GiB of memory, 22 GB on disk
```

Then serve:

```bash
uv run kansallisarkisto-mcp                         # stdio, for MCP clients
KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp   # streamable HTTP on :8000 (/mcp)
```

Over HTTP the server also answers `/health` (liveness) and `/ready` (readiness — 503 until
every served table is searchable, with the missing one named); see
[Observability](docs/development/observability.md).

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

Without a table the server still boots; every tool of that corpus returns a clear
missing-table message rather than crashing, and the boot log names the tables it did find.
The hosted Space is this image plus one setting: it copies the tables off its bucket mount at
boot, because lance cannot read that mount under load — see
[Deployment](docs/development/deployment.md#hugging-face-space).

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
MCP client ──/mcp──▶ ra_mcp_kansallisarkisto_mcp   (FastMCP tools per corpus + formatter + settings)
                        └─▶ ra_mcp_kansallisarkisto_lib   (LanceDB spine + record models + ingest + search)
                               ├─▶ data/df.lance             6,876 charters       (searchable_text indexed)
                               ├─▶ data/voudintilit.lance   98,945 pages         (searchable_text indexed)
                               └─▶ data/tuomiokirjat.lance   7.7M pages, 22 GB   (text indexed directly)
```

A uv workspace of two packages:

- `packages/kansallisarkisto-lib` — the LanceDB spine (`dataset.py`: connections, the
  full-text index settings, prefix expansion, the paginated search), one record model per
  corpus, the ingests, the search facades, and `astia.py`, which turns Astia's catalogue
  endpoints into the citations the export lacks. No MCP dependency, so it is usable on its own.
- `packages/kansallisarkisto-mcp` — FastMCP tools and their LLM-facing descriptions, one
  module per corpus, the formatter, env settings, server entry point.

The charters and the accounts index a derived `searchable_text` that folds the catalogue
fields in with the text, so an untranscribed charter or an untitled volume stays findable.
The court records index `text` itself: their catalogue fields are filters, and a duplicate of
7.7 million pages of text would cost 11 GB on disk and as much again in the Space's boot-time
copy.

## The data

The corpora come from **[Sisältöhaku](https://sisaltohaku.demo.kansallisarkisto.fi/)**, the
content-search demo service of **[Kansallisarkisto — the National Archives of
Finland](https://kansallisarkisto.fi/)**. `scripts/harvest.py` (`make harvest`) downloads
them through the service's own public JSON endpoints, the same ones the site's "download
results" button uses. The citations — archival references, and for voudintilit the page
links — come from **[Astia](https://astia.narc.fi/)**, Kansallisarkisto's digital archive,
through the public endpoints its own viewer calls; `scripts/fetch_astia.py` takes them once
per volume, at harvest time, never while serving.

Coverage is 98.25% of the live index. The shortfall is systematic rather than sampling:
Elasticsearch enforces a 10,000-document `from + size` ceiling per query and the public
frontend exposes only two filterable axes, so a handful of large facet cells cannot be
subdivided far enough to fit. The harvester records those as shortfalls instead of quietly
returning a short file. See [`docs/how-it-works/data-sources.md`](docs/how-it-works/data-sources.md)
for the corpus reference and the traps that shape this server's schema — page numbers with
gaps, inverted years, duplicated images, the volume that is an archive catalogue rather than
an account book.

A harvest is a **snapshot**, and the live index moves — `voudintilit` grew from 99,031 to
99,125 documents between two harvests. The live service is always the authority.

## Credit and licence

The records are the property of **Kansallisarkisto** and were published through its
[Sisältöhaku demo service](https://sisaltohaku.demo.kansallisarkisto.fi/) and its digital
archive [Astia](https://astia.narc.fi/). This repository holds no records — only the code
that downloads, indexes and searches them.

Cite **the archive**, not this snapshot, as the source of any document, and consult
Kansallisarkisto for terms of reuse and redistribution. Anything quoted from these corpora is
machine-recognised text and should be checked against the archive's own page images.

The code in this repository is Apache-2.0.

## Development

```bash
make check     # ruff format + lint + ty
make test      # pytest — no network, no corpus needed
make test-mcp  # end-to-end: production image + fixture tables + real MCP client (Dagger)
make ci        # the full pipeline GitHub Actions runs
```

The three supply-chain badges above describe the release pipeline in
[`publish.yml`](.github/workflows/publish.yml), each linking to the section of the security
docs that says how it is produced. Every release goes through it: the image
`riksarkivet/kansallisarkisto-mcp` is signed, and its SBOMs and provenance are attached to
the [release](https://github.com/AI-Riksarkivet/kansallisarkisto-mcp/releases).

The test fixtures in `packages/kansallisarkisto-lib/tests/fixtures/` are real records chosen
to cover each corpus's documented traps — 19 charters (untranscribed, unknown years, unlocated,
open and closed dating intervals, all four languages, and the one about Reval with no place
of issue), 12 bailiff-account pages (both collections, a page gap, the inverted-year volume,
the untitled catalogue, an empty page) and 18 court-record pages (a duplicated image, string
years and page numbers, the 1984–1895 outlier, an unlinked page, subseries) — with the Astia
snapshot lines for their volumes, so the whole suite runs without any harvest.
