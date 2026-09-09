---
icon: lucide/search
---

# Search Tips

## Search in the source language, in period spelling

The documents are early-modern Swedish, Latin and German — not Finnish. Orthography is
pre-reform and unstandardised.

| write | not | hits in `df` |
|---|---|---:|
| `bref` | `brev` | 257 |
| `konung` | `kung` | 279 |
| `gods` | | 1,147 |
| `Åbo` | `Turku` | 1,452 |
| `Stockholm` | | 742 |
| `biskop` | | 77 |

And in Latin: `ecclesia` 602, `littera` 356, `dominus` 244.

Swedish stemming is applied, so `konungen` finds `konung`, `konungs` and `konungavalit`.
Accents are folded, so `Abo` finds `Åbo`. Stop words are **kept**, unlike a normal Swedish
index: they are Latin content words here, and removing them cost `de` 1,735 documents, `den`
846 and `om` 1,133. Quoted phrases work — `"de ecclesia"` is narrower than `de ecclesia`.

## The edition's apparatus is stripped before indexing

Diplomatarium Fennicum is a scholarly edition, so its transcripts carry editorial apparatus
inline: footnote markers fused to the word they annotate (`Hundæbæth⁶`, `Karulj²`) and
editorial insertions in square brackets, sometimes mid-word (`Fi[n]llandh`, `eccl[esi]a`).
A tokeniser has no reason to treat either as punctuation, so `Hundæbæth⁶` indexed as a single
token and the plain word matched nothing — across 2,266 occurrences in 621 records, plus
4,801 bracketed forms in another 1,969.

The apparatus is now removed from the search text only. `transcript` still shows the edition
verbatim, because the apparatus is part of what a researcher is reading — so you may well see
a `⁶` in a result whose word you found without one.

## Several words mean all of them

A multi-word keyword requires every word; `"quoted words"` require that exact phrase.
`AND`, `OR` and `NOT` are **not** operators and are searched for literally, so `bref OR
littera` also matches the 51 charters containing the word `or`. Widen by dropping a word or
passing `match_all=false`, never by writing `OR`.

## Spelling is the main reason a search looks empty

Orthography was never standardised, so the same word appears in many forms and **a single
spelling finds one scribe's usage, not the word**. Measured on this corpus:

| you search | charters | the other spelling | charters | overlap |
|---|---:|---|---:|---:|
| `bref` | 257 | `breff` | 1,918 | **71** |
| `kyrkia` | 13 | `kirkio` | 82 | **1** |
| `konung` | 279 | `konungh` | 165 | **35** |

Two different mechanisms address this and the engine makes them **mutually exclusive**:

- **Stemming** (always on) handles *inflection*: `konungen` finds all 279 charters that stem
  to `konung`.
- **`fuzzy=1`** handles *orthography*: it takes `bref` from 257 charters to 2,212, and 96.9%
  of those still contain a real variant. `fuzzy=2` was tried and rejected — recall barely
  moves while precision falls to 67%.

A fuzzy term skips the analysis pipeline, so it is matched raw against stemmed index terms:
`konungen` with `fuzzy=1` collapses from 279 hits to **6**. So exact-plus-stemming is the
default, and when a search looks thin the right second attempt is `fuzzy=1` **on a base
form** — `konung`, not `konungen`.

## The DF number is searchable

`DF 1451` — or just `1451` — finds that charter. This is also what makes the four charters
with no transcript, place, index term or language reachable at all.

## A zero result means the term is absent

`kirkko` — the Finnish for "church" — appears in **zero** of the 6,876 charters. That is not
a broken index; the Finnish index vocabulary uses `Kirkolliset` and `Piispat`, and the
documents themselves say `ecclesia` or `kyrkia`. Do not smoke-test with a modern Finnish
word.

## Filter values are Finnish, and unaccented

`language` takes an exact label: `ruotsi` (Swedish, 3,045), `latina` (1,638), `saksa`
(German, 1,232), `venaja` (Russian, 89). Note **`venaja`, not `venäjä`** — the accented form
matches nothing. 27 charters carry more than one language, as compounds like `latina, ruotsi`.

`country` takes a Finnish country label as a substring: `Suomi` (2,249), `Ruotsi` (1,207),
`Italia` (467). 2,321 charters record no country.

`issuingplace` takes a place name as a substring, over a vocabulary of 499 values. 2,314
charters record no place. These are substring counts, which is what the filter does: `Rom`
(364) also matches the five charters issued at `Magliano Romano`.

**The naming is mixed, and this is the trap.** Finnish and Swedish places keep their
historical Swedish form — `Åbo` (815, not `Turku`), `Viborg` (311, not `Viipuri`),
`Nådendal` (134), `Raseborg` (120), `Tavastehus` (43). But places outside that realm are
recorded under their **modern** name:

| write | not | charters |
|---|---|---:|
| `Tallinn` | `Reval` | 197 |
| `Gdansk` | `Danzig` | 37 |
| `Tartu` | `Dorpat` | 5 |

`Reval`, `Danzig` and `Dorpat` return nothing at all. So the "use the period form" rule
that governs the *text* does not govern this *filter*: the text is medieval, the place
vocabulary is a modern cataloguer's.

## Untranscribed does not mean absent

2,464 of 6,876 charters — 36% — are catalogued but never transcribed. They are still
returned, marked `(catalogued but not transcribed)`, and remain findable by place, index term
and language, because the full-text index is built over those fields as well as the
transcript. An index over the transcript alone would silently lose a third of the corpus.

## Dates are intervals, and mostly open-ended

6,843 of 6,876 charters have no end year. `year_min` / `year_max` therefore test **interval
overlap** against a derived closed interval, not a comparison against the raw end year — a
filter written the obvious way would match 33 charters out of the whole corpus.

22 charters carry no year at all. A year-bounded search excludes them, as SQL excludes NULLs.

## The text is machine-recognised

These are OCR and handwritten-text-recognition outputs over a millennium of handwriting, not
proofread transcriptions. Expect misrecognised characters and broken word boundaries, and
check any quotation against the archive before presenting it as exact.
