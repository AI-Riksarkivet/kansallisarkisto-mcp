---
icon: lucide/wrench
---

# Tools

Four tools, two per corpus — all read-only and all closed-world: they query local LanceDB
tables and reach no network.

| tool | what it does |
|---|---|
| [`df_search`](df-search.md) | Full-text search over the 6,876 Diplomatarium Fennicum charters, narrowable by language, place, country and year range. |
| [`df_get_charter`](df-get-charter.md) | One charter's full transcript and catalogue record, by DF number. |
| [`voudintilit_search`](voudintilit-search.md) | Full-text search over the 98,945 pages of the Häme and Satakunta bailiff accounts, narrowable by bailiwick, account book and year range. |
| [`voudintilit_get_page`](voudintilit-get-page.md) | One page's full text, citation and Astia link, with the previous and next pages of its volume. |

## The workflow

### Diplomatarium Fennicum

1. `df_search` with a term in the source language and period spelling — Swedish, Latin or
   German, never modern Finnish.
2. Read the DF number off a hit. It is the citable identifier, and the only stable handle on
   a charter.
3. `df_get_charter` with that number for the full transcript.
4. Cite the DF number, and give the reader
   `https://df.kansallisarkisto.fi/document/<number>` — the archives' own edition of that
   charter, carrying the printed-edition references (FMU, REA) and any images.

### voudintilit

1. `voudintilit_search` with a term in early-modern Swedish — the accounts were kept in
   Swedish; only the catalogue titles are Finnish.
2. Read the citation off a hit — reference number, account book, year and page, such as
   **2372 Ylä-Satakunnan tilikirja 1585, p. 16** — and its page id.
3. `voudintilit_get_page` with the page id for the full text. Accounts run across pages, so
   follow the previous and next page ids it names.
4. Cite the page as the hit does, and give the reader its Astia link, which opens the page
   image in Kansallisarkisto's digital archive.

## What every result carries

### A charter

- The **DF number**, in bold, first.
- The **dating**, rendered as the source states it: a single year, a range, `by <year>`, or
  `undated`. It is never padded into a false range.
- The **place of issue** and country, or `place of issue unrecorded`.
- Language and index term where recorded.
- A ~400-character transcript snippet — or `(catalogued but not transcribed — no text
  available)` for the 36% of the corpus that has no transcript.

### A page

- The **citation**, in bold, first: reference number, account book, year and page. The one
  volume with no year — the Satakunta series' archive catalogue — is cited without one.
- The collection and the **page id**, `<volume>_<page>` — what `voudintilit_get_page` takes.
- A ~400-character text snippet, or `(no text recognised on this page)`.
- The **Astia link** to the page image, or `(no Astia link for this page)` where Astia lists
  no image for it.

Results end with a `More results available. Use offset=N` line when there is another page.

## Errors

Never exceptions — always a sentence:

- `Error: keyword must not be empty. Provide a search term, e.g. 'konung' or 'littera'.`
- `Error: year range is inverted — from/min (1500) must be <= to/max (1300). Swap the bounds.`
- `The df table is not available on this server. It is built … with make ingest-df, and
  mounted at KA_LANCEDB_URI; …` — a deployment state an operator can fix, so it is explained
  in full. The voudintilit tools say the same of their own table, naming
  `make fetch-astia ingest-voudintilit`.

Anything else is a server fault, and reports only its exception type:

- `Error: the search failed with an internal OSError. It has been logged; please report it
  if it persists.`

The message is deliberately withheld: every condition a caller could act on already has its
own sentence above, so the remainder would only disclose internals — lance errors quote the
on-disk dataset path. The full traceback is logged server-side.
