# tuomiokirjat — design

Status: in progress, 2026-09-10. Follows the voudintilit design; this note records only what
differs, and the measurements that decide how the corpus can be built and hosted.

## What the data is

Measured over the whole export (7,835,557 lines):

- **A page of a court record.** 12,284 volumes (`ay_id`), median 543 pages, the largest
  4,029. 223 archives (`aineistokokonaisuus`), 444 series (`pääsarja`) — from named town
  courts (*Turun raastuvanoikeuden tuomiokirjat*, 1623–1809) to the generic *Varsinaisten
  asioiden pöytäkirjat* (2.5M pages) and *Ilmoitusasioiden pöytäkirjat* (2.5M) of the
  19th-century district courts. Subseries on 746k pages. Years 1610–1931, the bulk 1750–1920;
  the 1910s alone are 1.1M pages.
- **Mixed types.** 315k rows carry their years as strings, 896k their page number; all
  parse. 703 pages have the end year before the start; 83 have no year; 139 are catalogued
  in the 1980s.
- **Duplicated images.** 60,000 `(volume, page)` pairs appear two or three times under
  distinct `objectID`s — same link, same years, identical text in 72% of cases and a
  re-recognised version in the rest. Sisältöhaku's own duplication, not the harvest's.
- **Links present** for 99.95% of pages; four pages have no text.

## Decisions

- **Page id is the export's `objectID`.** `<volume>_<page>` is not unique here. Volume and
  page are kept as columns for the neighbour lookup.
- **One record per image.** The ingest drops later occurrences of a `(volume, page)` pair,
  keeping the first. 60,000 fewer rows, and no page twice in a result.
- **The full-text index sits on `text`.** Nothing is worth folding in — the catalogue fields
  are filters — and a duplicate column over 7.8M pages costs 10 GB on disk and as much again
  in the Space's boot-time copy. The spine takes the column as `fts_column`.
- **Citation from Astia.** One metadata request per volume (the export already links every
  page) gives the signum — `a:1`, `g:87` — so a hit reads *series signum year, p. N*, with
  the archive on the line below. 12,284 requests at 0.3 s.
- **Tools:** `tuomiokirjat_search(keyword, offset, limit, collection?, series?, year_min?,
  year_max?, match_all, fuzzy)` with collection and series as case-insensitive substrings
  (223 and 444 values — too many for a fixed choice), and `tuomiokirjat_get_page(page_id)`
  with the previous and next existing pages of the volume.

## Measurements

| | 1M pages | 3M pages | 7.74M pages (final) |
|---|---|---|---|
| write | 25 s, 2.2 GB (with duplicate column) | 132 s, 7.6 GB | 231 s, 11 GB (text indexed directly) |
| FTS index, default (20 shards) | 46 s, 5.8 GiB peak, 1.2 GB | — | killed at 12 GiB |
| FTS index, 1 shard, 64 MiB partitions | 99 s, 2.8 GiB, 1.6 GB | 336 s, 4.1 GiB, 4.9 GB | — |
| FTS index, 1 shard, 256 MiB partitions | 87 s, 2.4 GiB, 1.1 GB | — | ~14 min, **6.6 GiB peak, 11 GB** |
| whole ingest | | | **18.4 min**, 21 GB |
| queries, 2 vCPU, 16 GB | warm 130–630 ms | warm 150–350 ms, cold 2.2 s | warm 180–390 ms, cold 0.3–3.8 s; phrase 13 ms; page by id 7 ms; neighbours 2 ms; **7.4 GB resident** |

So the index builds on this machine with the frugal settings — memory grows about 0.7 GiB
per million pages from a 2 GiB base — and 256 MiB partitions beat 64 MiB on both peak and
index size. The Space copied the whole 22 GB in 220 s on the v0.3.0 deploy — about 100 MB/s, so a
cold start is about four minutes, well within the 30-minute startup limit (the earlier
26 MB/s figure came from a 370 MB copy dominated by per-file cost).

## Decided by the measurements

- Build here; no larger machine needed.
- Ship the index on `text`: 21 GB in all, against 30+ GB with the duplicate column.
- The Space's free tier is enough: 7.4 GB resident against 16 GB; 21 GB copied onto a 50 GB
  disk.
