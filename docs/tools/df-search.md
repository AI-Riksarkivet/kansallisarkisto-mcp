---
icon: lucide/search
---

# `df_search`

Full-text search over Diplomatarium Fennicum: 6,876 medieval charters, letters and account
entries concerning Finland, 859–1530.

## Parameters

| parameter | type | default | notes |
|---|---|---|---|
| `keyword` | string | *(required)* | Search term, in the language of the documents and in period spelling. Swedish stemming and accent folding apply. Several words require **all** of them; `"quoted words"` require that exact phrase; a trailing `*` is a prefix (`lepros*`) and `\|` lists alternatives (`reval*\|reual*`). |
| `offset` | int ≥ 0 | `0` | Pagination start. |
| `limit` | int 1–100 | `25` | Results per page. |
| `language` | string | — | Exact, unaccented Finnish label: `ruotsi`, `latina`, `saksa`, `venaja`. |
| `issuingplace` | string | — | Case-insensitive substring of the place of **issue** — not the subject. Mixed vocabulary: historical Swedish for Finland and Sweden (`Åbo`, `Viborg`), **modern** elsewhere (`Tallinn` not `Reval`, `Gdansk` not `Danzig`). A third of the corpus records no place and is excluded. |
| `country` | string | — | Case-insensitive substring of the Finnish country label: `Suomi`, `Ruotsi`, `Italia`. |
| `year_min` | int | — | Earliest year the charter may fall in. |
| `year_max` | int | — | Latest year the charter may fall in. |
| `fuzzy` | int 0-2 | `0` | Edit distance per term. `1` catches spelling variants — the usual reason a search looks thin. Pass a base form: a fuzzy term skips stemming. It is whole-word distance, so it does not reach inflections; a prefix does. |
| `match_all` | bool | `true` | Require every word. `false` matches any word — useful when a term may be spelled differently, but the total then counts charters matching only one word. |
| `research_context` | string | — | A sentence on what the user is researching. Not searched; written to the server log beside the query, so an operator can see what the corpus is asked for. ra-mcp's tools take the same parameter. |

## Query syntax

Several words must **all** appear. `"Quoted words"` must appear as that exact phrase.

A trailing `*` is a **prefix**: `lepros*` matches `leprosi`, `leprosorum` and `leprosis`. It
needs at least 3 characters and expands to at most 300 forms (the most frequent; a capped
search says so in a note). This is how to search Latin and German, which the Swedish stemmer
never touches, and how to catch the spellings of a name. `|` separates **alternatives**
within a term: `bref|breff` matches either, `reval*|reual*|revel*` any of the three prefixes.
Alternatives are OR within the term and AND across terms, so
`lepros* reval*|reual*|revel*|reuel*|reffl*` means "leprosy, and Reval in any spelling".

**`AND`, `OR` and `NOT` are not operators** — they are matched as ordinary words. Writing
`bref OR littera` searches for `or` too, which on this corpus drags in 50 unrelated charters
that happen to contain the word. To widen, drop a word or pass `match_all=false`.

This matters for the total as much as the results. With any-word matching, `konung Stockholm`
reports 944 charters while only 77 contain both — BM25 still puts the good ones first (19 of
the first 20 contained both terms), but the total is a claim about the whole result set.

## How the filters behave

`language` is an **exact** match, because the labels are a closed vocabulary of 15 values —
a substring match on `latina` would also sweep in the compounds `latina, ruotsi` and
`latina, venaja`, which is a different question.

`issuingplace` and `country` are **substring** matches, case-insensitively, because the
place vocabulary is open (499 values) and historical spellings vary.

`issuingplace` is the place of **issue**, which is a different question from what a charter
is about. 2,314 charters (34%) record no place and are excluded whenever it is set, and a
letter about Tallinn written in Åbo is issued at Åbo. DF 173 — the dean and chapter of Reval
asking the bishop of Åbo to support their leper house, 1279 — has no recorded place and is
unreachable through `issuingplace="Tallinn"` by any keyword. A filtered search therefore ends
with a note saying so, and for the catalogue's modern names it gives the period forms to
search in the text instead: Tallinn is `reval*|reual*|revel*|reuel*|reffl*`, Gdansk
`dantz*|dantsk*`, Tartu `darpt*|darbt*|dorpt*|tarbat*`.

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
df_search(keyword="littera", language="latina", country="Italia")
df_search(keyword="\"de ecclesia\"")                       # exact phrase
df_search(keyword="lepros*")                                # prefix: leprosi, leprosorum, …
df_search(keyword="lepros* reval*|reual*|revel*|reuel*")   # leprosy AND Reval, any spelling
df_search(keyword="Perugia Lateranen", match_all=False)   # either word
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
