---
icon: lucide/code
---

# API Overview

`ra_mcp_kansallisarkisto_lib` is usable on its own — it has no MCP dependency.

```python
import lancedb
from ra_mcp_kansallisarkisto_lib import DfSearch, ingest_df, resolve_lancedb_uri

db = lancedb.connect(resolve_lancedb_uri())
search = DfSearch(db)

result = search.search("konung", issuingplace="Åbo", year_min=1300, year_max=1400)
print(result.total_hits)
for record in result.records:
    print(record["df"], record["year_from"], record["issuingplace"])

charter = search.get_charter(1451)
```

## Modules

| module | contents |
|---|---|
| `config` | Table names, paging bounds, `resolve_lancedb_uri()`. |
| `dataset` | The shared LanceDB spine: `SearchResult`, `get_lancedb`, index builders, `lancedb_fts_search`, SQL predicate builders, `format_results`. |
| `models` | [`DfRecord`](models.md) — the source-JSON conventions, normalised. |
| `ingest` | [`ingest_df`](ingest.md) and the declared Arrow schema. |
| `search_operations` | [`DfSearch`](search.md). |

The MCP package adds `errors` (the missing-table error, shared by `tools` and `df_tool`
without a cycle), `formatter`, `settings`, `routes` and `server`.

## Resolving the database

`resolve_lancedb_uri()` returns, in order:

1. `KA_LANCEDB_URI`, if set — any URI lancedb accepts, including `s3://` and `gs://`.
2. `<project root>/data`, when running from a clone.
3. `/data`, the container mount point.

It resolves at call time, not import time, so a test or a container can set the variable
after import and still be honoured.
