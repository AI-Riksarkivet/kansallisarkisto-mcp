---
icon: lucide/scroll-text
---

# kansallisarkisto-mcp

kansallisarkisto-mcp is an MCP server over the **Sisältöhaku** corpora of Kansallisarkisto,
the National Archives of Finland. It gives an AI assistant full-text search across
machine-transcribed archival text, served locally from LanceDB rather than from a live API.

Three corpora: **Diplomatarium Fennicum** (`df`), the scholarly edition of 6,876 medieval
charters, letters and account entries concerning Finland, 859–1530; **`voudintilit`**, 98,945
pages of the Swedish crown's bailiff accounts for Häme and Satakunta, 1539–1635; and
**`tuomiokirjat`**, 7.8 million pages of Finnish lower-court records from 223 archives,
1610–1931. The pages of the two paged corpora are cited by their archival reference and
linked to their image in Astia, Kansallisarkisto's digital archive — every voudintilit page,
and all but a fraction of a percent of the court records.

## The text is not in Finnish

Finland was part of the Swedish realm until 1809, and these records were kept in the
administrative language of the day. The documents are **early-modern Swedish, Latin and
German**. Only the catalogue metadata — index terms, language and country labels — is
Finnish.

This is the single most consequential fact about searching this material. A query in modern
Finnish returns nothing, and so does a query in modern Swedish spelling: use `bref` not
`brev`, `konung` not `kung`, `Åbo` not `Turku`.

That governs the text. The `issuingplace` **filter** follows a different rule, and it is the
one that catches people out — see [Search Tips](how-it-works/search-tips.md): Finnish and
Swedish places keep their historical Swedish form, but places beyond that realm are catalogued
under their modern name, so `Tallinn` finds 197 charters and `Reval` finds none.

## The tools

- **`df_search`** — full-text search over the charters, narrowable by language, place and
  country of issue, and year range. Swedish stemming and accent folding are applied. Each hit
  leads with its DF number, the citable identifier; page with `offset`.
- **`df_get_charter`** — one charter's full transcript and catalogue record by DF number.
- **`voudintilit_search`** — full-text search over the bailiff-account pages, narrowable by
  bailiwick, account book and year range. Each hit is one page, led by its citation —
  reference number, account book, year and page — and linked to its image in Astia.
- **`voudintilit_get_page`** — one page's full text by page id, with the previous and next
  pages of its volume.
- **`tuomiokirjat_search`** — full-text search over the court-record pages, narrowable by
  archive, series and year range. Each hit is one page, led by its citation — series, signum,
  year and page — with the archive beneath, and linked to its image in Astia.
- **`tuomiokirjat_get_page`** — one court-record page's full text by page id, with the
  previous and next pages of its volume.

Every DF number resolves to `https://df.kansallisarkisto.fi/document/<number>`, the National
Archives' own edition of that charter — the link to hand a reader alongside the number.

## Quick connect

The server is hosted on Hugging Face:

```bash
claude mcp add --transport http kansallisarkisto https://riksarkivet-kansallisarkisto-mcp.hf.space/mcp
```

For claude.ai, add a custom connector with the same URL. To run it yourself from a clone over
stdio instead:

```bash
make install
make harvest
make ingest-df
claude mcp add kansallisarkisto -- uv run kansallisarkisto-mcp
```

See [Local Install](getting-started/local.md) for the container route and the data it needs.

## Where to go next

- [Connect](getting-started/index.md) — wire an MCP client to a local or containerised server.
- [How it Works](how-it-works/index.md) — the FastMCP server, the LanceDB spine, settings.
- [The Corpora](how-it-works/data-sources.md) — what the data is, and the traps that shaped the schema.
- [Tools](tools/index.md) — full parameter reference.
- [Development](development/index.md) — tests, CI, image, release.
