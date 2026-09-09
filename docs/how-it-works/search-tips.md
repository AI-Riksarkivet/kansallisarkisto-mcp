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
| `konung` | `kung` | 277 |
| `gods` | | 1,147 |
| `Åbo` | `Turku` | 1,451 |
| `Stockholm` | | 742 |
| `biskop` | | 74 |

And in Latin: `ecclesia` 600, `littera` 355, `dominus` 242.

Swedish stemming is applied, so `konungen` finds `konung`, `konungs` and `konungavalit`.
Accents are folded, so `Abo` finds `Åbo`.

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

`issuingplace` takes the historical place name as a substring: `Åbo` (815), `Stockholm`
(687), `Rom` (359). 2,314 charters record no place.

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
