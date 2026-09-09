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
| `voudintilit` | 98,945 | 131 MB | 1539–1634 | Bailiff accounts | not yet |
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
| `issuingplace` | string | `issuingplace` | Place of issue, historical form |
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
indexable text and check the charter comes back. The answer, after three fixes it prompted,
is **all but four of 6,876** — and those four carry no transcript, place, index term or
language at all, so there is nothing for any index to hold. They remain reachable by DF
number through `df_get_charter`, and `test_retrieval_quality.py` pins that.

The sweep found three ways documents had been silently unfindable:

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
