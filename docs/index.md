---
icon: lucide/scroll-text
---

# kansallisarkisto-mcp

kansallisarkisto-mcp is an MCP server over the **Sisältöhaku** corpora of Kansallisarkisto,
the National Archives of Finland. It gives an AI assistant full-text search across
machine-transcribed archival text, served locally from LanceDB rather than from a live API.

Currently serving **Diplomatarium Fennicum** (`df`) — the scholarly edition of 6,876 medieval
charters, letters and account entries concerning Finland, 859–1530.

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

Every DF number resolves to `https://df.kansallisarkisto.fi/document/<number>`, the National
Archives' own edition of that charter — the link to hand a reader alongside the number.

## Quick connect

There is no hosted endpoint yet. Run it from a clone over stdio:

```bash
make install
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
