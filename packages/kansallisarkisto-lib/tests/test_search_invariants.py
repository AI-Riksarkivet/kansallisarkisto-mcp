"""Properties that must hold for any query, and the index settings they rest on.

`test_retrieval_quality.py` pins specific things that were once broken. This file
pins the *shape* of search: relationships that have to hold whatever the query is,
so a regression shows up even on terms nobody thought to write a case for.

Three of these guard decisions that were expensive to reach and are cheap to undo
by editing one keyword argument — stop words kept, positions on, fuzzy off — so
they are asserted against the index the ingest actually built, not against the
source that was supposed to build it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ra_mcp_kansallisarkisto_lib.config import DF_TABLE
from ra_mcp_kansallisarkisto_lib.dataset import DEFAULT_FUZZINESS, FTS_COLUMN

# Terms that exist in the fixture and are their own stem, so fuzzy widening is
# comparable with exact matching (an inflected term is not — fuzzy skips the
# analyser, which is the whole reason DEFAULT_FUZZINESS is 0).
#
# "Stockholm" was here and matched nothing in the fixture, which made two of the
# subset tests below pass vacuously: an empty set is a subset of anything. Every
# such test now asserts it had something to compare.
BASE_TERMS = ["Åbo", "ecclesia"]


def _fts_config(db) -> dict:
    for index in db.open_table(DF_TABLE).list_indices():
        if index.columns == [FTS_COLUMN]:
            return index.index_details
    raise AssertionError(f"no full-text index on {FTS_COLUMN}")


# --- the index is built the way the reasoning assumes -------------------------


def test_full_text_index_is_configured_as_intended(db, df_table):
    """Each of these is a decision with a measured argument behind it, and each
    is one keyword argument away from being silently reverted."""
    config = _fts_config(db)
    assert config["language"] == "Swedish"
    assert config["stem"] is True
    # Swedish stop words are Latin content words here; removing them cost "de"
    # 1,735 documents, "den" 846 and "om" 1,133.
    assert config["remove_stop_words"] is False
    # Without positions a quoted query raises rather than searching.
    assert config["with_position"] is True
    # Place names appear accented and unaccented across four centuries.
    assert config["ascii_folding"] is True
    # Long Swedish compounds would otherwise be dropped and become unsearchable.
    assert config["max_token_length"] == 64


def test_the_filtered_columns_are_indexed(db, df_table):
    """Filters push down to these; without the index each becomes a full scan."""
    indexed = {idx.columns[0]: idx.index_type for idx in db.open_table(DF_TABLE).list_indices()}
    assert indexed.get("df_number") == "BTree"
    assert indexed.get("year_from") == "BTree"
    assert indexed.get("year_to") == "BTree"
    assert indexed.get("language") == "Bitmap"
    assert indexed.get("issuingplacecountry") == "Bitmap"


def test_nothing_is_left_unindexed(db, df_table):
    """The search runs with fast_search(), which skips unindexed rows entirely.

    That is safe only because the table is built once and never appended to. If
    rows ever arrive without a reindex, searches start silently missing them —
    the failure would look like a data problem, not a query one.
    """
    for index in db.open_table(DF_TABLE).list_indices():
        assert index.num_unindexed_rows == 0, f"{index.name} has unindexed rows; fast_search would skip them"


def test_the_fuzzy_default_matches_what_the_docstrings_claim():
    """The constant and the prose around it disagreed once; nothing tests prose."""
    from ra_mcp_kansallisarkisto_lib import search_operations

    assert DEFAULT_FUZZINESS == 0
    assert "0 by default" in (search_operations.DfSearch.search.__doc__ or "")


# --- relationships that hold for any query ------------------------------------


@pytest.mark.parametrize("term", BASE_TERMS)
def test_requiring_all_terms_narrows(search, term):
    """AND results are a subset of OR results — never merely different."""
    narrow = {r["df"] for r in search.search(f"{term} latina", limit=500).records}
    wide = {r["df"] for r in search.search(f"{term} latina", limit=500, match_all=False).records}
    assert narrow, "nothing to compare — the subset check would pass vacuously"
    assert narrow <= wide
    assert len(wide) > len(narrow), "OR must actually be wider, or this proves nothing"


@pytest.mark.parametrize("term", BASE_TERMS)
def test_fuzzy_widens_a_base_form(search, term):
    """Only for a base form: a fuzzy term skips the analyser, so an inflected
    query legitimately returns *fewer* hits with fuzziness on."""
    exact = {r["df"] for r in search.search(term, limit=500).records}
    fuzzy = {r["df"] for r in search.search(term, limit=500, fuzzy=1).records}
    assert exact, "nothing to compare — the subset check would pass vacuously"
    assert exact <= fuzzy


def test_every_filter_narrows(search):
    """A filter may only remove rows from the unfiltered result set."""
    everything = {r["df"] for r in search.search("Åbo", limit=500).records}
    assert everything
    for kwargs in ({"language": "latina"}, {"country": "Suomi"}, {"issuingplace": "Åbo"}, {"year_min": 1300, "year_max": 1400}):
        narrowed = {r["df"] for r in search.search("Åbo", limit=500, **kwargs).records}
        assert narrowed, f"{kwargs} matched nothing; the subset check would pass vacuously"
        assert narrowed <= everything, f"{kwargs} returned rows the unfiltered search did not"


def test_filters_are_honoured_by_every_row_returned(search):
    """Not just narrower — correct. A filter that silently does nothing would
    still pass the subset check above."""
    assert search.search("Åbo", limit=500, language="latina").records
    for record in search.search("Åbo", limit=500, language="latina").records:
        assert record["language"] == "latina"
    for record in search.search("Åbo", limit=500, country="Suomi").records:
        assert "suomi" in record["issuingplacecountry"].lower()
    for record in search.search("Åbo", limit=500, year_min=1300, year_max=1400).records:
        assert record["year_from"] <= 1400 and record["year_to"] >= 1300


def test_pages_tile_the_result_set_without_gaps_or_repeats(search):
    """Pagination slices one ranked set; if it ever went back to per-page
    queries, BM25 ties would make pages drop and duplicate rows."""
    everything = [r["df"] for r in search.search("Åbo", limit=500).records]
    assert len(everything) > 4
    paged: list[str] = []
    for offset in range(0, len(everything), 2):
        paged.extend(r["df"] for r in search.search("Åbo", limit=2, offset=offset).records)
    assert paged == everything
    assert len(set(paged)) == len(paged)


def test_repeating_a_query_gives_the_same_order(search):
    """Stable ordering is what makes offset paging meaningful."""
    first = [r["df"] for r in search.search("Åbo", limit=50).records]
    second = [r["df"] for r in search.search("Åbo", limit=50).records]
    assert first == second


@pytest.mark.parametrize(("a", "b"), [("Åbo", "åbo"), ("Åbo", "ÅBO"), ("Åbo", "Abo"), ("ecclesia", "ECCLESIA")])
def test_case_and_accents_do_not_change_the_result(search, a, b):
    """Lower-casing and ascii folding are index-time settings; if either were
    turned off, only a query in the "wrong" form would notice."""
    left = {r["df"] for r in search.search(a, limit=500).records}
    assert left, "nothing to compare — the equality check would pass vacuously"
    assert left == {r["df"] for r in search.search(b, limit=500).records}


def test_the_page_never_exceeds_the_limit_or_the_total(search):
    result = search.search("Åbo", limit=3)
    assert len(result.records) <= 3
    assert len(result.records) <= result.total_hits
    assert result.total_hits >= 1


def test_paging_past_the_end_keeps_the_total_honest(search):
    """An empty page is not the same as no matches, and the formatter says so."""
    total = search.search("Åbo", limit=1).total_hits
    past = search.search("Åbo", limit=10, offset=10_000)
    assert past.records == []
    assert past.total_hits == total


def test_a_phrase_is_never_wider_than_its_words(search):
    loose = search.search("de ecclesia", match_all=False).total_hits
    assert search.search('"de ecclesia"').total_hits <= loose


# --- inputs that must not reach the caller as an exception --------------------


def test_fuzzy_on_a_quoted_phrase_is_refused_rather_than_ignored(search):
    """The parser takes no fuzziness argument, so honouring both is impossible.
    Dropping one silently is what the tool descriptions were just cleaned of."""
    with pytest.raises(ValueError, match="quoted phrase"):
        search.search('"de ecclesia"', fuzzy=1)


@pytest.mark.parametrize("df_number", [2**31, 2**63, -(2**31) - 1, "not a number", None])
def test_get_charter_returns_none_rather_than_raising(search, df_number):
    """df_number is an int32 column; out-of-range values failed predicate
    resolution and surfaced to the model as an internal error."""
    assert search.get_charter(df_number) is None


@pytest.mark.parametrize("bad", [("", ValueError), ("   ", ValueError)])
def test_blank_keywords_raise_valueerror(search, bad):
    keyword, exc = bad
    with pytest.raises(exc):
        search.search(keyword)


@pytest.mark.parametrize(("offset", "limit"), [(-1, 25), (0, 0), (0, -5)])
def test_impossible_paging_is_rejected(search, offset, limit):
    """Left through, these produce an empty page beside a nonzero total, and the
    formatter then reports "no results" for a search that matched."""
    with pytest.raises(ValueError):
        search.search("Åbo", offset=offset, limit=limit)


# --- against the real corpus, when it is present ------------------------------

_CORPUS = Path(".data/df/df.jsonl.gz")
_corpus_only = pytest.mark.skipif(not _CORPUS.exists(), reason="full corpus not harvested")


@pytest.fixture(scope="module")
def corpus_search():
    """DfSearch over the harvested corpus, if it has been ingested."""
    import lancedb

    from ra_mcp_kansallisarkisto_lib import DfSearch, resolve_lancedb_uri
    from ra_mcp_kansallisarkisto_lib.dataset import table_names

    db = lancedb.connect(resolve_lancedb_uri())
    if DF_TABLE not in table_names(db):
        pytest.skip("df table not ingested")
    return DfSearch(db)


@_corpus_only
def test_a_finnish_word_absent_from_the_corpus_still_returns_nothing(corpus_search):
    """`kirkko` appears in none of the 6,876 charters — the index vocabulary uses
    `Kirkolliset`. It is the documented smoke test that must NOT be used as one,
    and a nonzero result here would mean the analyser had started matching
    loosely."""
    assert corpus_search.search("kirkko").total_hits == 0
    assert corpus_search.search("Kirkolliset").total_hits > 100


@_corpus_only
@pytest.mark.parametrize("stop_word", ["de", "den", "om"])
def test_stop_words_reach_hundreds_of_charters(corpus_search, stop_word):
    """Each returned zero while a Swedish analyser was removing them."""
    assert corpus_search.search(stop_word).total_hits > 500


@_corpus_only
def test_fuzzy_reaches_the_spelling_variants_exact_matching_misses(corpus_search):
    """`bref` and `breff` are the same word and share only 71 of their charters."""
    exact = corpus_search.search("bref").total_hits
    widened = corpus_search.search("bref", fuzzy=1).total_hits
    assert widened > exact * 4, f"fuzzy widened {exact} to only {widened}"


@_corpus_only
def test_a_charter_is_findable_by_its_citation(corpus_search):
    """Closes the gap for the four charters with nothing else to index."""
    for number in ("18", "4245", "4777", "6623"):
        assert any(h["df"] == number for h in corpus_search.search(f"DF {number}", limit=50).records)
