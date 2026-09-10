---
icon: lucide/database
---

# The Corpora

Three full-text corpora were harvested from the Sisältöhaku demo service of Kansallisarkisto,
the National Archives of Finland. Together they hold **7,941,378 OCR/HTR-recognised
documents** — 19.4 GB of text — spanning **859 to 1938**.

| corpus | documents | text | period | content | ingested |
|---|---:|---:|---|---|---|
| `tuomiokirjat` | 7,835,557 | 19.25 GB | 1600s–1900s | Court records | not yet |
| `voudintilit` | 98,945 | 131 MB | 1539–1635 | Bailiff accounts | **yes** |
| `df` | 6,876 | 7.4 MB | 859–1530 | Medieval charters | **yes** |

The harvest lives in `.data/`, which is git-ignored: 6.3 GB of gzipped JSON Lines has no
place in a repository, and it is a snapshot that should be re-harvested rather than
versioned. `scripts/harvest.py` does that — `make harvest`, or
`uv run python scripts/harvest.py --index all` — writing the same three files per corpus
that the July 2026 harvest produced. Re-harvesting `df` reproduces the stored snapshot
record for record.

### How the harvester works

Two public POST endpoints sit behind the frontend. `/api/search` takes Algolia-style
requests and answers with **true, uncapped** counts and facet values; `/api/export-all`
returns the documents, and is what the site's own download button calls. Counts have to come
from the first because the second caps both its results *and its reported total* at 10,000 —
so a saturated response cannot be distinguished from a complete one by looking at it.

Slicing therefore escalates only as far as it must, sized against real counts:

| slice key | filter |
|---|---|
| `all` | none — the whole corpus fits (this is `df`) |
| `y=1539` | `range: {alkuvuosi: {min, max}}` |
| `c=<collection>\|y=1539` | that, plus `refinementList` on the collection facet |

Two encoding details are load-bearing, and both fail *silently* — the filter is dropped and
an unfiltered page comes back looking entirely valid. The year range must be the object form
`{"min": y, "max": y}`; the `"1539:1539"` string that InstantSearch itself serialises is
accepted and ignored. And the collection facet is named `Aineistokokonaisuus` in
`tuomiokirjat` but `Aineistokokonaisuus_vt` in `voudintilit`.

Each finished slice is appended as its own gzip member and then recorded in
`checkpoint.json`, so `--resume` continues an interrupted run. A crash between those two
steps can duplicate a single slice; `--verify` (or `make verify-data`) checks that the
`objectID`s are still unique.

## Provenance

The corpora are downloaded from
[Sisältöhaku](https://sisaltohaku.demo.kansallisarkisto.fi/), the content-search demo
service of [Kansallisarkisto](https://kansallisarkisto.fi/), through the same public JSON
endpoints the site's own "download results" button uses. Run `make harvest`, or
`uv run python scripts/harvest.py --index all`. Each corpus directory gets the harvester's
`report.json` recording what was and was not retrieved, and `checkpoint.json` recording the
slice-by-slice progress that makes a run resumable.

Coverage is **98.25%** of the live index (7,941,378 of 8,082,496). The gap is systematic, not
random: Elasticsearch enforces a 10,000-document `from + size` ceiling per query and the
public frontend exposes only two filterable axes, so 22 facet cells exceed the ceiling and
their surplus is unreachable by this route — 128,297 of them from the Vyborg town court
archive alone. The documented Elasticsearch API at `es.demo.kansallisarkisto.fi` has no such
ceiling; with an API key those records are retrievable.

**A harvest is a snapshot, and the index moves.** Between two harvests `voudintilit` went
from 99,031 to 99,125 documents. Nothing in a harvested file signals that drift, so anything
Kansallisarkisto has added, corrected or re-recognised since the run is simply absent. Re-run
the harvester when currency matters; the live service is always the authority.

## `df` — Diplomatarium Fennicum

The scholarly edition of medieval documents relating to Finland — charters, letters, account
entries and narrative sources. The only corpus of the three with geographic coordinates.

| source field | type | becomes | meaning |
|---|---|---|---|
| `objectID` | string | `object_id` | Elasticsearch document id |
| `df` | string | `df`, `df_number` | DF number — the citable charter identifier |
| `transcript` | string | `transcript` | Transcribed text |
| `indexterm` | string | `indexterm` | Subject classification (Finnish) |
| `issuingplace` | string | `issuingplace` | Place of issue — historical Swedish form for Finland and Sweden, modern name elsewhere |
| `issuingplacecountry` | string | `issuingplacecountry` | Country of issue (Finnish) |
| `language` | string | `language` | Document language (Finnish label) |
| `dating_start_year` | int | `dating_start_year`, `year_from` | Earliest possible date |
| `dating_end_year` | int | `dating_end_year`, `year_to` | Latest possible date |
| `_geoloc` | object | `lat`, `lng` | Coordinates of the issuing place |

Plus a derived `searchable_text`, which the full-text index is built over.

## The traps, and what the schema does about them

The corpus has four documented conventions that quietly break a naive loader. Each is handled
at ingest rather than left for every query to remember.

**`0` in a year field means "unknown", not year zero.** Stored as a literal 0 it pollutes
every date range. The ingest maps it to null.

**6,843 of 6,876 charters (99.5%) have `dating_end_year == 0`.** A filter written as
`dating_end_year <= X` therefore matches at most 33 charters, because SQL excludes nulls from
comparisons — silently reducing a date-bounded search to 0.5% of the corpus. The ingest
derives a closed interval (`year_from`, `year_to`) so the filter is a plain two-column
overlap test.

**2,464 charters (36%) have an empty `transcript`.** They are catalogued but untranscribed.
`searchable_text` folds in place, country, index term and language, so they stay findable —
and the formatter labels them, so an empty transcript reads as "not transcribed" rather than
as an empty record.

**Language labels are unaccented Finnish**: the value is `venaja`, not `venäjä`. Filtering on
the accented form returns nothing. The tool description says so; nothing rewrites the value.

Two further points shape the ingest. `_geoloc` is populated for 4,142 charters (60%); the
rest have both `lat` and `lng` null, never one alone — which is why the schema is declared
rather than inferred, since a batch of entirely-unlocated charters would infer as a null
column and fail to merge with a later float batch. And the `file_id` field, which the other
two corpora carry, is a zero-padded string in `voudintilit` and an integer in `tuomiokirjat`
— another reason the schema is pinned per corpus.

## Can everything be found?

Every record in the corpus was swept: take a distinctive word from each charter's own
indexable text and check the charter comes back. The answer, after the fixes it prompted, is
**all 6,876**.

Four charters carry no transcript, place, index term or language at all, so there was
nothing for any index to hold and no keyword could reach them. The citation is now part of
the search text — written as `df <number>`, so the way a researcher actually types it, `DF
18`, matches — which closes the gap without changing any content-query count.

The sweep found three further ways documents had been silently unfindable:

| what | scale | fix |
|---|---|---|
| Words fused to footnote superscripts (`Hundæbæth⁶`) or split by editorial brackets (`eccl[esi]a`) | 2,266 occurrences in 621 records; 4,801 in 1,969 | apparatus stripped from the search text, kept in `transcript` |
| `de`, `den`, `om` returned nothing — a Swedish analyser had removed them as stop words, though they are Latin content words | tokens in 1,735 / 846 / 1,133 documents | stop-word removal turned off for this corpus |
| Quoted phrase queries **raised** instead of searching, so the MCP layer reported an internal error | every phrase query | positions added to the index |

A fourth problem is not a bug but a property of the material, and it is the largest of all:
**spelling was never standardised**, so `bref` and `breff` are the same word yet share only
71 of their 2,104 charters. No index setting fixes that — stemming handles inflection, not
orthography — so `df_search` exposes `fuzzy`, which takes `bref` from 257 charters to 2,212
at 96.9% precision. It is opt-in because the engine makes fuzzy and stemming mutually
exclusive: a fuzzy term skips analysis and `konungen` drops from 279 hits to 6. See
[Search Tips](search-tips.md).

Recovering the fused words moved the verified reference counts slightly upward — `konung`
277 → 279, `ecclesia` 600 → 602 — which is what recovered recall looks like. `DF 3453`, for
instance, reads `eccl[esi]a` in the source and was previously unreachable by `ecclesia`.

## `voudintilit` — bailiff accounts

The Swedish crown's bailiff accounts for the Häme and Satakunta bailiwicks, 1539–1635 — the
yearly account books in which the bailiffs recorded the taxes they collected. A record is a
**page**, not a document: 98,945 pages from 1,582 volumes, each volume one bailiwick's
accounts for one year. Every volume carries exactly one title and one year pair.

| source field | type | becomes | meaning |
|---|---|---|---|
| `objectID` | string | `page_id` | Always `<ay_id>_<file_id>` — the handle `voudintilit_get_page` takes |
| `ay_id` | int | `volume_id` | The volume; Astia's `aineistoId` |
| `file_id` | zero-padded string | `file_id`, `page` | The page within the volume, always four digits |
| `aineistokokonaisuus` | string | `collection` | *Hämeen voutikuntien tilejä* (54,560 pages) or *Satakunnan voutikuntien tilejä* (44,385) |
| `arkistoyksikkö` | string | `account_book` | The account book's title — 292 distinct, such as *Sääksmäen voutikunnan tilikirja* or *Maakirja* |
| `alkuvuosi` | int | `year_start`, `year_from` | First year |
| `loppuvuosi` | int | `year_end`, `year_to` | Last year |
| `teksti` | string | `text` | Transcribed text |

Plus `searchable_text` — the text, account book and collection, the same three fields
Sisältöhaku's own search covers — and the `reference`, `series` and `url` joined from Astia.
Columns are named in English rather than after the source: LanceDB filter predicates name
their columns bare, and `arkistoyksikkö` is not an identifier to trust its parser with.

### Citations come from Astia

The export carries no link and no archival reference, and neither does Sisältöhaku's own
interface. Astia, Kansallisarkisto's digital archive, has both, through the two public JSON
endpoints its viewer calls: one gives a volume's reference number (`tunnisteet`, e.g. `2372`),
title, dates, fonds and series; the other lists every image in the volume, titled
`Tiedosto N`, with the file id the viewer addresses it by. Page N is `Tiedosto N`, so every
page gets an exact link:

```
https://astia.narc.fi/uusiastia/viewer/?fileId=<file id>&aineistoId=<volume>
```

`scripts/fetch_astia.py` (`make fetch-astia`) fetches both once per volume — about 3,200
requests — into `.data/voudintilit/astia.jsonl`, and the ingest joins them. That happens at
harvest time, never while serving: the endpoints are undocumented, and a serving path that
depended on them would inherit every change Astia makes. A volume the snapshot lacks is
ingested without a reference or link rather than dropped.

### Its traps

**Page numbers have gaps.** 106 volumes skip pages and 318 do not start at page 1, because
Astia holds images Sisältöhaku has no text for — volume 1576091152 has 138 images and 136
pages of text. `voudintilit_get_page` therefore names the nearest *existing* page on either
side, not N ± 1.

**The collection labels are Finnish genitives.** `Satakunta` as a substring matches neither
*Satakunnan voutikuntien tilejä* nor anything else, so the filter is a fixed choice — `hame`
or `satakunta` — mapped to the full label.

**One volume's years are inverted.** Reference 2523, *Ylä-Satakunnan tilikirja*, reads
1615–1516, in Astia's own catalogue as well. The end year precedes the corpus, so it is the
typo: the ingest keeps the start year for both bounds rather than stretching its 27 pages
across a century.

**One volume is not an account book.** The 66 pages with `0` for both years are all the
Satakunta series' archive catalogue — *Satakunnan voudintilien arkistoluettelo*, reference
103 — untitled in the export and named by Astia. They have no year, so any year filter leaves
them out.

**Three pages have no text.** They stay findable by account book and collection, which are
indexed with the text, and are labelled rather than shown blank.

### Can every page be found?

Every page was swept the way the `df` charters were: search the page's rarest word and check
the page comes back, retrying with its next-rarest words where the index splits a word
differently. **96,978 of the 98,945 pages** come back by a word of their own. The other 1,967
are inconclusive rather than lost — once stemmed, even their rarest words return more than the
100 results the sweep read, so the page may simply rank beyond them. None was missed.

## Choosing an analyzer

A Swedish stemmer is right for `tuomiokirjat` and `voudintilit`. For `df` it is a 44%
plurality choice: 2,870 of its charters are Latin or German, and a Swedish stemmer mis-stems
them. It remains the best single choice, and `build_fts_index` takes a `language` argument
for corpora where a different one wins.

## Licence and attribution

The underlying records are the property of Kansallisarkisto and were published through its
Sisältöhaku demo service. This is a derived snapshot. Consult Kansallisarkisto for terms of
reuse and redistribution, and cite the archive — not this snapshot — as the source of any
document.
