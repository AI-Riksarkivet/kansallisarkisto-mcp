---
icon: lucide/cog
---

# MCP & Tools

## Shape

```
MCP client ──/mcp──▶ ra_mcp_kansallisarkisto_mcp   FastMCP tools, formatter, settings
                        └─▶ ra_mcp_kansallisarkisto_lib   LanceDB spine, ingest, search
                               └─▶ data/df   LanceDB table, built from the harvested export
```

Two workspace packages:

- **`packages/kansallisarkisto-lib`** — everything that would be useful without MCP: the
  record model, the ingest, the search operations and the shared LanceDB spine. No FastMCP
  dependency.
- **`packages/kansallisarkisto-mcp`** — the tool definitions and their LLM-facing
  descriptions, the plain-text formatter, env settings and the server entry point.

## The LanceDB spine

`ra_mcp_kansallisarkisto_lib.dataset` owns the parts every corpus shares, so `voudintilit` and
`tuomiokirjat` inherit them rather than growing their own copies:

- **`SearchResult`** — one page plus a true total.
- **`get_lancedb`** — a process-cached, thread-safe connection per URI. LanceDB connections
  have no `close()`; one per URI for the process lifetime is the intended usage.
- **`build_fts_index`** — the Swedish full-text index: stemming, accent folding, a raised
  token-length limit, and stop-word removal deliberately **off** (Swedish stop words are
  Latin content words here — removing them cost `de` 1,735 documents). Each is passed
  explicitly rather than left to a lancedb default that has moved between releases.
- **`build_scalar_indexes`** — BTree on ordered columns, Bitmap on low-cardinality
  categoricals, so a `.where()` filter is an index lookup and not a column scan.
- **`lancedb_fts_search`** — the paginated search itself.
- **predicate builders** — `equals`, `at_least`, `text_contains`, `combine` … so filter SQL
  is quoted correctly in one place instead of re-implemented per corpus.
- **`format_results`** — the result envelope every corpus formatter shares.

## Pagination and totals

lancedb exposes no count API on a full-text query. The search therefore fetches the ranked
result set once (up to 10,000 rows) and slices the requested page from it. That gives two
things a per-query `.offset()` cannot:

- a **true** `total_hits`, rather than a count capped at `limit + offset`;
- **stable** pagination. BM25 score ties reorder between queries, so separate offset queries
  drop and duplicate rows; slicing one ranked set does not.

It costs something, and the cost is paid on every search: up to 10,000 rows are materialised
to be counted and all but `limit` of them thrown away. Two things keep that honest. The
full-text column is projected out of the result — it only repeats text the row already
carries, and dropping it halves the payload. And when the count actually reaches the bound,
`total_is_capped` says so, and the total is rendered as `10000+` instead of being passed off
as exact. `df` (6,876 rows) can never reach it; `tuomiokirjat` (7.8M) routinely would.

Filters are pushed into LanceDB as a SQL `where` clause, so both the total and the page are
computed over the filtered set — not by post-filtering a truncated window in Python.

## Failure behaviour

Nothing raises out to the client. An empty keyword, an inverted year range, a missing table
or an unexpected lance error all come back as a sentence the model can relay or act on; an
exception would reach it as a protocol error it cannot.

The server boots without data on purpose — the image ships empty and the table is mounted or
ingested separately — and logs at startup which tables the configured URI actually holds, so
a wrong URI is visible immediately rather than on the first tool call.
