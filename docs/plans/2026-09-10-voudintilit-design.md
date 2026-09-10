# voudintilit — design

Status: approved 2026-09-10. Ships in v0.2.0 together with the landing-page fix and boot-time
staging already in the working tree.

## Goal

Serve the second Sisältöhaku corpus, `voudintilit` — 98,945 machine-transcribed pages of
bailiff accounts from Häme and Satakunta, 1539–1635 — with the same search quality and the
same citation discipline as `df`. Then measure `tuomiokirjat` (7.8M pages) before deciding
how to host it.

## What the data is

Measured over the whole harvest (`.data/voudintilit/voudintilit.jsonl.gz`):

- **A record is a page, not a document.** 1,582 volumes (`ay_id`), each one account book for
  one year: every volume has exactly one title (`arkistoyksikkö`, 292 distinct) and one
  year pair. `file_id` is the page number within the volume, always four digits.
  `objectID` is always `<ay_id>_<file_id>`.
- **Page numbers have gaps** in 106 volumes, and 318 volumes do not start at page 1: Astia
  holds images Sisältöhaku has no text for. "Next page" means the next existing page.
- **Two collections** (`aineistokokonaisuus`): *Hämeen voutikuntien tilejä* (54,560) and
  *Satakunnan voutikuntien tilejä* (44,385). Finnish genitives — a substring `Satakunta`
  matches neither.
- **Years:** 66 pages have `0` for both (all in one volume, which Astia identifies as the
  Satakunta series' archive catalogue, not an account book); 27 pages carry an inverted
  pair 1615–1516 (all in one volume — the end year precedes the corpus, so it is the typo).
- **Text:** 3 pages empty; median 1,242 characters; early-modern Swedish.
- **No link and no archival reference** in the export, and none in Sisältöhaku's own UI.

## Citation: an Astia snapshot

Astia's public JSON endpoints — the ones its own viewer calls — supply what the export lacks:

- `ws/json/json_tiedot.php?tyyppi=aineisto&id=<ay_id>` → reference (`tunnisteet`, e.g.
  `2372`), title, dates, fonds and series.
- `ws/json/json_tiedostot.php?id=<ay_id>` → every image, titled `Tiedosto N`, with its Astia
  file id. Page N is `Tiedosto N`, so each page gets an exact viewer link:
  `https://astia.narc.fi/uusiastia/viewer/?fileId=<file id>&aineistoId=<ay_id>`.

Fetched once per volume at harvest time (≈3,200 polite, resumable requests) into
`.data/voudintilit/astia.jsonl`, never at serving time. A volume Astia cannot serve is
ingested without a link or reference rather than dropped.

A hit reads: **2372 Ylä-Satakunnan tilikirja 1585, p. 16** — collection — page id — snippet
— Astia link.

## Components

| layer | new | reused |
|---|---|---|
| harvest | `astia.py` (parse image list + metadata), `scripts/fetch_astia.py` | — |
| model | `VoudintilitRecord` (page id, volume id, page, collection, account book, reference, years, text, url, searchable_text) | `_clean`, `_year` |
| ingest | `ingest_voudintilit`, `VOUDINTILIT_SCHEMA`, `make ingest-voudintilit` | `build_fts_index`, `build_scalar_indexes`, batch streaming |
| search | `VoudintilitSearch.search`, `.get_page` (with neighbours) | `lancedb_fts_search`, predicate builders |
| tools | `voudintilit_search`, `voudintilit_get_page` | `_answer`, `require_keyword`, `require_ordered_range`, `format_results` |
| server | a lazy search facade per table; per-table boot check; `/ready` requires every table | staging, routes |

Year handling: `0` → null; an inverted pair keeps the start year for both bounds. Indexes:
Swedish FTS with the `df` settings (stemming, stop words kept, positions, accent folding);
BTree on volume id, page, year_from, year_to; Bitmap on collection.

`collection` is a fixed choice (`hame` / `satakunta`) mapped to the full label.
`account_book` is a case-insensitive substring over the 292 titles.

## Errors

Each tool reports its own missing table. A missing Astia record means no link and no
reference, stated in the output rather than left blank. `get_page` on an unknown id is a
normal "no such page" answer.

## Testing

Test-first throughout. A fixture of real pages covering the traps above; unit tests per
layer; retrieval-quality checks; a findability sweep over all 98,945 pages as `df` has; the
MCP smoke test extended to the new tools; `dagger call test-mcp`.

## Deploy

`voudintilit.lance` beside `df.lance` in the `Riksarkivet/kansallisarkisto` bucket; the Space
stages both at boot. README, docs site, landing page and server instructions updated.

## Afterwards: tuomiokirjat

A full trial ingest here, recording table and index size, build time, peak memory, and query
latency under the Space's limits (`--cpus=2 --memory=16g`). Hosting is decided from those
numbers. Its records already carry Astia page links.
