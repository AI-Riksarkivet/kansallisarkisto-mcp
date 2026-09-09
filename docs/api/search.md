---
icon: lucide/search-code
---

# Search

## `DfSearch`

```python
DfSearch(db, *, table_name="df")
```

### `search`

```python
search(
    keyword, *, limit=25, offset=0,
    language=None, issuingplace=None, country=None,
    year_min=None, year_max=None,
) -> SearchResult
```

Raises `ValueError` for a blank keyword, a negative offset or a limit below 1 — guarded
centrally, so a bad page cannot produce an empty result with a nonzero total and a broken
`offset=-N` footer.

### `get_charter`

```python
get_charter(df_number: str | int) -> dict | None
```

Returns the charter row, or `None` for an unknown or non-numeric number.

## `SearchResult`

| field | meaning |
|---|---|
| `records` | The page, as a list of row dicts — every column except `searchable_text`, plus `_score`. |
| `total_hits` | True match count over the filtered set, up to `MAX_TOTAL_COUNT` (10,000). |
| `total_is_capped` | True when the count reached that bound, i.e. `total_hits` is a floor. `format_results` then renders it as `10000+` rather than passing it off as exact. Never true for `df` (6,876 rows); routine for `tuomiokirjat`. |
| `keyword`, `offset`, `limit` | Echoed back, so a formatter needs no other state. |

### Projection

`lancedb_fts_search` fetches the whole ranked set to count it and discards all but
`limit` rows, so what each row carries is a real cost. `columns` defaults to every column
except `searchable_text`, which only repeats text the row already has — measured on `df`,
that halves a 1,451-hit query from 6.1 MB to 3.3 MB. `_score` is added explicitly, since
lancedb still auto-projects it when a `select` omits it but warns that it will stop.

## The spine

`lancedb_fts_search(db, table_name, keyword, *, limit, offset=0, where=None)` is what
`DfSearch` calls, and what the other two corpora will call. Filters arrive as a SQL `where`
string built by the predicate helpers:

| helper | produces |
|---|---|
| `equals(col, v)` | `col = 'v'` (bare for ints) |
| `at_least(col, v)` / `at_most(col, v)` | `col >= v` / `col <= v` |
| `text_contains(col, v)` | `lower(col) LIKE '%v%' ESCAPE '\'` |
| `any_of(a, b)` | `(a OR b)` |
| `combine(a, None, b)` | `a AND b`, or `None` when nothing is set |

Two quoting details are load-bearing. String literals double their single quotes, so a place
name containing an apostrophe cannot break the predicate. And column names are emitted
**bare**, never double-quoted: LanceDB's filter parser reads `"col"` as a string literal,
SQLite-style, so quoting an identifier silently matches nothing.

`text_contains` also escapes LIKE wildcards in the value, so a literal `%` in a filter
matches a literal `%` rather than "anything".
