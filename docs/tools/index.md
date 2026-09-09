---
icon: lucide/wrench
---

# Tools

Two tools, both read-only and both closed-world — they query a local LanceDB table and reach
no network.

| tool | what it does |
|---|---|
| [`df_search`](df-search.md) | Full-text search over the 6,876 Diplomatarium Fennicum charters, narrowable by language, place, country and year range. |
| [`df_get_charter`](df-get-charter.md) | One charter's full transcript and catalogue record, by DF number. |

## The workflow

1. `df_search` with a term in the source language and period spelling — Swedish, Latin or
   German, never modern Finnish.
2. Read the DF number off a hit. It is the citable identifier, and the only stable handle on
   a charter.
3. `df_get_charter` with that number for the full transcript.

## What every result carries

- The **DF number**, in bold, first.
- The **dating**, rendered as the source states it: a single year, a range, `by <year>`, or
  `undated`. It is never padded into a false range.
- The **place of issue** and country, or `place of issue unrecorded`.
- Language and index term where recorded.
- A ~400-character transcript snippet — or `(catalogued but not transcribed — no text
  available)` for the 36% of the corpus that has no transcript.

Results end with a `More results available. Use offset=N` line when there is another page.

## Errors

Never exceptions — always a sentence:

- `Error: keyword must not be empty. Provide a search term, e.g. 'konung' or 'littera'.`
- `Error: year range is inverted — from/min (1500) must be <= to/max (1300). Swap the bounds.`
- `The df table is not available on this server. It is built … with make ingest-df, and
  mounted at KA_LANCEDB_URI; …` — a deployment state an operator can fix, so it is explained
  in full.

Anything else is a server fault, and reports only its exception type:

- `Error: the search failed with an internal OSError. It has been logged; please report it
  if it persists.`

The message is deliberately withheld: every condition a caller could act on already has its
own sentence above, so the remainder would only disclose internals — lance errors quote the
on-disk dataset path. The full traceback is logged server-side.
