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
