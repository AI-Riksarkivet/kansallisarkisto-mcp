---
icon: lucide/search
---

# `df_search`

Full-text search over Diplomatarium Fennicum: 6,876 medieval charters, letters and account
entries concerning Finland, 859–1530.

## Parameters

| parameter | type | default | notes |
|---|---|---|---|
| `keyword` | string | *(required)* | Search term, in the language of the documents and in period spelling. Swedish stemming and accent folding apply. Supports boolean syntax: `bref OR littera`. |
| `offset` | int ≥ 0 | `0` | Pagination start. |
| `limit` | int 1–100 | `25` | Results per page. |
| `language` | string | — | Exact, unaccented Finnish label: `ruotsi`, `latina`, `saksa`, `venaja`. |
| `issuingplace` | string | — | Case-insensitive substring of the historical place name: `Åbo`, `Stockholm`, `Rom`. |
| `country` | string | — | Case-insensitive substring of the Finnish country label: `Suomi`, `Ruotsi`, `Italia`. |
| `year_min` | int | — | Earliest year the charter may fall in. |
| `year_max` | int | — | Latest year the charter may fall in. |

## How the filters behave

`language` is an **exact** match, because the labels are a closed vocabulary of 15 values —
a substring match on `latina` would also sweep in the compounds `latina, ruotsi` and
`latina, venaja`, which is a different question.

`issuingplace` and `country` are **substring** matches, case-insensitively, because the
place vocabulary is open (499 values) and historical spellings vary.

`year_min` / `year_max` test **interval overlap**: a charter is returned when its dating
interval intersects `[year_min, year_max]`. Because 99.5% of charters have no end year, the
interval used is a derived closed one — a charter dated 1347 with no end year is treated as
`[1347, 1347]`, not as extending indefinitely. Charters with no year at all (22 of them) are
excluded from any year-bounded search.

An inverted range is rejected up front rather than returning a silent empty result.

## Examples

```
df_search(keyword="konung")
df_search(keyword="konung", issuingplace="Åbo", year_min=1300, year_max=1400)
df_search(keyword="bref OR littera", language="latina", country="Italia")
df_search(keyword="Åbo", limit=50, offset=50)
```

## Output

```
Diplomatarium Fennicum search results for 'konung': showing 2 of 277 records (offset 0)

**DF 2671** — 1446 — Stockholm, Ruotsi
  language: ruotsi · index term: Paikallishallinto, Asiakirjat
  (Konung Kristofer kallar marsken Karl Knutsson till fejd emot konung Erik på Gotland …

**DF 670** — 1357 — Åbo, Suomi
  language: latina · index term: Piispat, Asiakirjat
  (catalogued but not transcribed — no text available)

More results available. Use offset=25 to see the next page.
```

The total is a true count of matches, not the size of the current page.
