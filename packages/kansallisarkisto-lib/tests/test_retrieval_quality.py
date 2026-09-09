"""Can a researcher actually find what is in the corpus?

Unit tests answer "does the code do what it says". These answer the prior
question — whether what it says is enough — and they exist because auditing the
full 6,876-charter corpus turned up three ways documents were silently
unfindable. Each is pinned here against the fixture so it cannot come back.

The audit's standing results, for reference:

- 5 of 6,876 records could not be retrieved by any keyword. Four have no
  transcript, place, index term or language at all, so there is nothing to index;
  they remain reachable by DF number. The fifth was a false alarm in the audit,
  not a gap.
- 2,266 word occurrences across 621 records (14% of the transcribed ones) were
  fused to a superscript footnote marker, and 4,801 more across 1,969 records
  were split by editorial brackets. Both are scholarly-edition apparatus, and
  both made the plain word unfindable.
- "de" (a token in 1,735 documents), "den" (846) and "om" (1,133) returned
  nothing, because a Swedish analyser removed them as stop words even though they
  are Latin content words in a corpus that is 42% Latin and German.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from ra_mcp_kansallisarkisto_lib.models import DfRecord, strip_editorial_apparatus

DF_FIXTURE = Path(__file__).parent / "fixtures" / "df_sample.jsonl"


def _fixture_records() -> list[dict]:
    return [json.loads(line) for line in DF_FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- the editorial apparatus, which is markup rather than text ----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A footnote marker fused to the word it annotates. The tokeniser has no
        # reason to treat a superscript as punctuation, so "hundæbæth⁶" indexes
        # as one token and the plain word never matches.
        ("Hundæbæth⁶", "Hundæbæth"),
        ("Karulj² de ecclesia", "Karulj de ecclesia"),
        # Editorial insertion *inside* a word: two useless tokens without this.
        ("Fi[n]llandh⁷", "Finllandh"),
        ("eccl[esi]a", "ecclesia"),
        # A scribal abbreviation ring, same problem.
        ("M°CCC°XL", "MCCCXL"),
        # Plain text must survive untouched.
        ("Konung Magnus", "Konung Magnus"),
    ],
)
def test_strip_editorial_apparatus(raw, expected):
    assert strip_editorial_apparatus(raw) == expected


def test_searchable_text_strips_apparatus_but_the_transcript_keeps_it():
    """The edition's apparatus is part of what a researcher reads, so it is
    removed from the index only — never from what gets displayed."""
    record = DfRecord.from_json({"objectID": "x", "df": "404", "transcript": "Hermanni Hundæbæth⁶ et Fi[n]llandh⁷"})
    assert "Hundæbæth⁶" in record.transcript
    assert "⁶" not in record.searchable_text
    assert "Hundæbæth" in record.searchable_text
    assert "Finllandh" in record.searchable_text


def test_fixture_actually_contains_the_apparatus_this_guards_against():
    """If DF 404 ever leaves the fixture, the tests below would pass vacuously."""
    marked = [r for r in _fixture_records() if any(c in r["transcript"] for c in "⁰¹²³⁴⁵⁶⁷⁸⁹°")]
    bracketed = [r for r in _fixture_records() if "[" in r["transcript"]]
    assert marked, "fixture no longer covers footnote markers"
    assert bracketed, "fixture no longer covers editorial brackets"


# --- what the index does with it ---------------------------------------------


def test_a_word_fused_to_a_footnote_marker_is_findable(search):
    """Was 0 hits before the apparatus was stripped."""
    assert search.search("Hundæbæth").total_hits >= 1


def test_a_word_split_by_editorial_brackets_is_findable(search):
    """`Fi[n]llandh` indexed as two junk tokens; now it is one real word."""
    assert search.search("Finllandh").total_hits >= 1


def test_stop_words_are_searchable(search):
    """Swedish stop words are Latin content words in a corpus that is 42% Latin
    and German. Removing them cost `de` alone 1,735 documents."""
    assert search.search("de").total_hits >= 1


def test_phrase_queries_work_rather_than_raising(search):
    """Without positions in the index a quoted query raises, and the MCP layer
    can only report that as an internal error for a perfectly ordinary search."""
    result = search.search('"de ecclesia"')
    assert result.total_hits >= 1


def test_a_phrase_is_narrower_than_its_words(search):
    """Proves the phrase is really being matched as a phrase, not as loose terms."""
    phrase = search.search('"de ecclesia"').total_hits
    loose = search.search("de ecclesia").total_hits
    assert phrase < loose


# --- the standing guarantee ---------------------------------------------------


def test_every_record_with_indexable_content_is_retrievable(search):
    """The corpus-wide sweep, in miniature.

    For each fixture record, take a distinctive word from its own searchable
    text and check the record comes back. This is what caught the footnote-marker
    gap in the first place.
    """
    unreachable = []
    for raw in _fixture_records():
        record = DfRecord.from_json(raw)
        words = [w for w in record.searchable_text.split() if len(w) > 6 and w.isalpha()]
        if not words:
            continue
        for word in words[:5]:
            if any(hit["df"] == record.df for hit in search.search(word, limit=100).records):
                break
        else:
            unreachable.append((record.df, words[:5]))
    assert not unreachable, f"records not retrievable by their own words: {unreachable}"


def test_records_with_no_indexable_content_are_still_reachable_by_number(search):
    """Four charters in the corpus carry no transcript, place, index term or
    language. Nothing can index them, so search will never find them — but they
    are real records and must not vanish entirely."""
    empty = [r for r in _fixture_records() if not DfRecord.from_json(r).searchable_text.strip()]
    assert empty, "fixture no longer covers the empty-record case"
    for raw in empty:
        assert search.get_charter(raw["df"]) is not None


@pytest.mark.parametrize("query", ['"unclosed phrase', "konung]", "konung\\", "!!!", "*", "konung^2", "  konung  "])
def test_awkward_queries_do_not_raise(search, query):
    """The keyword arrives from a model, so it will eventually contain quotes,
    brackets and operators. None of them may reach the caller as an exception."""
    search.search(query)


def test_the_corpus_snapshot_is_intact():
    """Guards the ingest input itself: the fixture is real data, and a mangled
    encoding would quietly weaken every test above."""
    records = _fixture_records()
    assert len(records) == len({r["objectID"] for r in records}), "duplicate objectIDs"
    assert any("Åbo" in r["issuingplace"] for r in records), "Swedish characters did not survive"


@pytest.mark.skipif(not Path(".data/df/df.jsonl.gz").exists(), reason="full corpus not harvested")
def test_full_corpus_reachability_is_understood():
    """When the real export is present, hold the line on the audited numbers.

    Not a mock: this reads the harvested corpus and recomputes how many records
    have nothing indexable. If a re-harvest changes that, it should be a decision
    rather than a surprise.
    """
    with gzip.open(".data/df/df.jsonl.gz", "rt", encoding="utf-8") as handle:
        records = [DfRecord.from_json(json.loads(line)) for line in handle if line.strip()]
    empty = [r.df for r in records if not r.searchable_text.strip()]
    assert len(records) >= 6876
    assert len(empty) <= 4, f"more records became unindexable: {empty}"


# --- what a multi-word query means -------------------------------------------


def test_several_words_require_all_of_them(search):
    """The engine's default is OR, which made the total a claim nobody meant:
    "konung Stockholm" matched 944 charters corpus-wide, nearly all on one word."""
    both = search.search("Åbo latina")
    either = search.search("Åbo latina", match_all=False)
    assert both.total_hits < either.total_hits
    for record in both.records:
        assert record["language"] == "latina"


def test_match_all_false_widens(search):
    narrow = search.search("Perugia Lateranen").total_hits
    wide = search.search("Perugia Lateranen", match_all=False).total_hits
    assert wide > narrow


@pytest.mark.parametrize("operator", ["OR", "AND", "NOT"])
def test_boolean_words_are_not_operators(search, operator):
    """They are matched as ordinary words, so the tool descriptions must never
    suggest them: writing "OR" once pulled in 50 charters containing "or"."""
    plain = search.search("Åbo Suomi", match_all=False).total_hits
    with_word = search.search(f"Åbo {operator} Suomi", match_all=False).total_hits
    assert with_word >= plain, "if this ever behaves as an operator, revisit the tool guidance"


def test_a_quoted_phrase_still_works_with_match_all(search):
    """Quoted input goes to the query parser rather than the AND matcher —
    routing it through the matcher turned '"de ecclesia"' into 496 hits."""
    assert search.search('"de ecclesia"').total_hits == search.search('"de ecclesia"', match_all=False).total_hits


# --- spelling variation, the corpus's largest recall problem ------------------


def test_fuzzy_is_opt_in_so_stemming_keeps_working(search):
    """The engine makes fuzzy and stemming mutually exclusive: a fuzzy term skips
    the analysis pipeline and is matched raw against stemmed index terms. On the
    full corpus "konungen" collapses from 279 hits to 6 with fuzzy=1, which is
    why exact-plus-stemming is the default and fuzzy is an explicit widening."""
    from ra_mcp_kansallisarkisto_lib.dataset import DEFAULT_FUZZINESS

    assert DEFAULT_FUZZINESS == 0


def test_fuzzy_widens_to_spelling_variants(search):
    """Orthography is unstandardised, so one spelling finds one scribe. On the
    full corpus this is the difference between 257 and 2,212 charters."""
    exact = search.search("kirkia", fuzzy=0).total_hits
    widened = search.search("kirkia", fuzzy=1).total_hits
    assert widened >= exact
