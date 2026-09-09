---
icon: lucide/box
---

# Models

## `DfRecord`

A pydantic model of one Diplomatarium Fennicum charter. Field names follow the source JSON,
so a row can be traced back to the export line it came from; four columns are derived.

```python
DfRecord.from_json(row: dict) -> DfRecord
```

Builds a record from one line of `df.jsonl.gz`.

### Source fields

`object_id`, `df`, `transcript`, `indexterm`, `issuingplace`, `issuingplacecountry`,
`language`, `dating_start_year`, `dating_end_year`.

Absent text fields are empty strings, not nulls — the source convention, preserved.

### Derived fields

**`df_number`** — `df` parsed as an int. The DF number is numeric for all 6,876 charters, but
as a string `"10"` sorts before `"2"`. The int form is what a range filter or an ordering
uses; the string stays authoritative for citation.

**`year_from` / `year_to`** — the dating interval with the unknowns closed, so a date filter
is a plain two-column overlap test rather than a `COALESCE` over nullable columns. A charter
with a start year and no end year is dated to that single year, so `year_from == year_to`;
an absent start year with a known end is treated symmetrically. Both are `None` only when the
source gives no year at all.

**`lat` / `lng`** — `_geoloc` flattened. The source nests them and sets both to null together
(never one alone) for the 2,734 unlocated charters, which flat nullable columns represent
exactly while remaining filterable.

**`searchable_text`** (a property) — the transcript plus place, country, index term and
language. Deliberately more than the transcript: 2,464 charters are catalogued but
untranscribed, and an index over `transcript` alone would make them unreachable by search
even though they are perfectly findable by their catalogue fields.

### Year normalisation

`0` in a year field means "unknown", not year 0. Left as a literal 0 it silently pollutes
every date range — 6,843 of the 6,876 charters carry `dating_end_year == 0` — so it is
normalised to `None` on the way in, together with blanks and unparseable values.
