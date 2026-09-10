---
icon: lucide/search
---

# `voudintilit_search`

Full-text search over **voudintilit** — 98,945 machine-transcribed pages of the Swedish
crown's bailiff accounts for the Häme and Satakunta bailiwicks, 1539–1635. Each hit is one
**page** of an account book, led by its archival citation and linked to its image in Astia.

## Parameters

| parameter | type | default | notes |
|---|---|---|---|
| `keyword` | string | *(required)* | Search term in early-modern Swedish and period spelling. Swedish stemming and accent folding apply. Several words require **all** of them; `"quoted words"` require that exact phrase; `bref\|breff` matches either spelling. A trailing `*` is not available here — the corpus is too large for a vocabulary — so list spellings, or use `fuzzy`. The account-book title and collection are indexed with the page text. |
| `offset` | int ≥ 0 | `0` | Pagination start. |
| `limit` | int 1–100 | `25` | Results per page. |
| `collection` | `hame` \| `satakunta` | — | *Hämeen voutikuntien tilejä* (54,560 pages) or *Satakunnan voutikuntien tilejä* (44,385). |
| `account_book` | string | — | Case-insensitive substring of the Finnish title, matching every title that contains it: `Sääksmäen` covers 28 titles (14,125 pages), `Maakirja` the 80 land-register titles (32,330). |
| `year_min` | int | — | Earliest year of the account. |
| `year_max` | int | — | Latest year of the account. |
| `fuzzy` | int 0-2 | `0` | Edit distance per term. Spelling was never standardised, so `1` is the second attempt when a search looks thin. Pass a base form: a fuzzy term skips stemming. |
| `match_all` | bool | `true` | Require every word. `false` matches any word — and the total then counts pages matching only one. |

## How the filters behave

`collection` is a **fixed choice**, mapped to the full label, because the labels are Finnish
genitives: `Satakunta` as a substring would match neither. A value outside the two is refused
rather than quietly matching nothing.

`account_book` is a **substring**, case-insensitively. The same bailiwick's accounts are
spread over many titles, so a substring deliberately gathers them — which is also why it
seldom narrows to a single book.

`year_min` / `year_max` test **interval overlap** over the account's year range. One Satakunta
volume, reference 2523, is catalogued as 1615–1516 — in Astia too; the end year precedes the
corpus, so it counts as 1615. The Satakunta series' archive catalogue has no year at all and
is left out whenever a year is set.

An inverted range is rejected up front rather than returning a silent empty result.

## Examples

```
voudintilit_search(keyword="konung")
voudintilit_search(keyword="smör", collection="hame", year_min=1540, year_max=1560)
voudintilit_search(keyword="smör", account_book="Sääksmäen")
voudintilit_search(keyword="\"konung Mattz breff\"")     # exact phrase
voudintilit_search(keyword="breff", fuzzy=1)            # spelling variants
```

## Output

```
Voudintilit search results for 'smör': showing 2 of 2856 records (offset 0)

**3853 Mustialan kartanon voutikunnan tilikirja 1558, p. 53**
  Hämeen voutikuntien tilejä · page 1571635026_0053
  3854. 52 Peder Poyttz anno 59 Vtgifftenn på Smör Leffuereret till Stocholms slåttz waruhees …
  https://astia.narc.fi/uusiastia/viewer/?fileId=6788701113&aineistoId=1571635026

**3673 Tilikirja 1541, p. 82**
  Hämeen voutikuntien tilejä · page 1570716497_0082
  Opbörde på Smör Inuentariu 10 t:nor 6 lb Bolmadz Smör 4 t:nor 11 1/2 lb …
  https://astia.narc.fi/uusiastia/viewer/?fileId=6779587805&aineistoId=1570716497

More results available. Use offset=2 to see the next page.
```

Every hit leads with its **citation** — reference number, account book, year and page — then
the collection and the page id, a snippet, and the page image in Astia. Pass the page id to
[`voudintilit_get_page`](voudintilit-get-page.md) for the whole page.

The total is a true count of matches up to 10,000, and reads `10000+` beyond it: `smör` alone,
across both collections, passes the cap.
