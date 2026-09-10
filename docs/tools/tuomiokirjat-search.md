---
icon: lucide/search
---

# `tuomiokirjat_search`

Full-text search over **tuomiokirjat** — 7.8 million machine-transcribed pages of Finnish
lower-court records, 1610–1931, from 223 archives: the judgement books and minutes of the town
courts (*raastuvanoikeus*), the district courts (*kihlakunnanoikeus*, by *tuomiokunta*), the
town bailiffs' courts (*kämnerinoikeus*), the land-partition courts and two appeal courts. Each
hit is one **page** of a court volume, led by its archival citation and linked to its image in
Astia.

## Parameters

| parameter | type | default | notes |
|---|---|---|---|
| `keyword` | string | *(required)* | Search term in Swedish and period spelling. Swedish stemming and accent folding apply. Several words require **all** of them; `"quoted words"` require that exact phrase; `bref\|breff` matches either spelling. A trailing `*` is not available here — the corpus is too large for a vocabulary — so list spellings, or use `fuzzy`. Only the page text is indexed. |
| `offset` | int ≥ 0 | `0` | Pagination start. |
| `limit` | int 1–100 | `25` | Results per page. |
| `collection` | string | — | The archive, as a case-insensitive substring over 223 Finnish names: `Turun raastuvanoikeuden`, `Etelä-Pohjanmaan`, `Viipurin hovioikeuden`; `tuomiokunnan` alone reaches every district court. |
| `series` | string | — | The series, as a case-insensitive substring over 444 names. For the 17th–18th-century town courts it names the court (`Turun raastuvanoikeuden tuomiokirjat`); for the 19th–20th-century district courts the record type — `Varsinaisten asioiden pöytäkirjat` (cases) or `Ilmoitusasioiden pöytäkirjat` (registrations). |
| `year_min` | int | — | Earliest year of the volume. |
| `year_max` | int | — | Latest year of the volume. |
| `fuzzy` | int 0-2 | `0` | Edit distance per term. Spelling was never standardised, so `1` is the second attempt when a search looks thin. Pass a base form: a fuzzy term skips stemming. |
| `match_all` | bool | `true` | Require every word. `false` matches any word — and the total then counts pages matching only one. |

## How the filters behave

`collection` and `series` are **substrings**, case-insensitively, because 223 and 444 values
are too many for a fixed choice and a court's name is how a caller reaches for them. The two
work together: for a 19th-century district court the archive names the district and the series
the record type, so `collection="Lappeen"` with `series="Varsinaisten"` is that district's
court cases.

`year_min` / `year_max` test **interval overlap** over the volume's year range. 83 pages have no
year and are left out whenever a year is set. 703 are catalogued with the end before the start;
they are dated by whichever bound falls within the corpus — so the 139 pages catalogued
1984–1895 filter as 1895, and a volume reading 1899–1898 as 1899.

An inverted range is rejected up front rather than returning a silent empty result.

## Examples

```
tuomiokirjat_search(keyword="hustru", series="Turun raastuvanoikeuden", year_min=1650, year_max=1660)
tuomiokirjat_search(keyword="Larsson", collection="Raastuvanoikeuksien renovoidut")
tuomiokirjat_search(keyword="lagfart", collection="Lappeen", series="Ilmoitusasioiden")
tuomiokirjat_search(keyword="\"then 3 Maji\"")                   # exact phrase
tuomiokirjat_search(keyword="breff", fuzzy=1, year_min=1620, year_max=1640)
```

## Output

```
Tuomiokirjat search results for 'Larsson': showing 1 of 1 records (offset 0)

**Porin raastuvanoikeuden tuomiokirjat a:1 1622–1639, p. 66**
  Raastuvanoikeuksien renovoidut tuomiokirjat · page PpblIZcBCao99UPKvl9-
  Erich Larsson fick löftte förståndin Rätta 32 den 3 Februaryis heer Rådstugu och Smgård …
  https://astia.narc.fi/uusiastia/viewer/?fileId=5929607974&aineistoId=2317506414
```

Every hit leads with its **citation** — the series, the volume's signum, the year and the page
— then the archive (and subseries, where there is one) and the page id, a snippet, and the
page image in Astia. Pass the page id to [`tuomiokirjat_get_page`](tuomiokirjat-get-page.md)
for the whole page.

The total is a true count of matches up to 10,000, and reads `10000+` beyond it. On a corpus
this size most common words pass the cap, so narrow by collection, series and years before
paging: the total is then a number that means something.
