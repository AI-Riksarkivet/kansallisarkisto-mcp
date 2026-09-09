"""Tests for DfSearch over the ingested sample."""

import pytest


def test_search_returns_results(search):
    result = search.search("konung")
    assert result.total_hits >= 1
    assert result.records


def test_search_is_stemmed(search):
    """Swedish stemming: an inflected query must find the base form and vice versa."""
    assert search.search("konungen").total_hits >= 1


def test_search_folds_accents(search):
    """Place names appear accented and unaccented across four centuries of spelling."""
    assert search.search("Abo").total_hits == search.search("Åbo").total_hits > 0


def test_search_finds_untranscribed_charters(search):
    """36% of df is catalogued but untranscribed — those must stay findable.

    An index over `transcript` alone would silently drop them.
    """
    result = search.search("Åbo", limit=100)
    assert any(not rec["transcript"] for rec in result.records)


def test_search_empty_keyword_raises(search):
    with pytest.raises(ValueError):
        search.search("")


def test_search_whitespace_keyword_raises(search):
    with pytest.raises(ValueError):
        search.search("   ")


def test_search_negative_offset_raises(search):
    with pytest.raises(ValueError):
        search.search("Åbo", offset=-1)


def test_search_zero_limit_raises(search):
    with pytest.raises(ValueError):
        search.search("Åbo", limit=0)


def test_search_pagination_is_a_slice_of_one_ranked_set(search):
    """Page 2 must continue page 1, not repeat or skip it."""
    everything = search.search("Åbo", limit=100)
    assert everything.total_hits > 2

    first = search.search("Åbo", limit=2, offset=0)
    second = search.search("Åbo", limit=2, offset=2)
    assert [r["df"] for r in first.records] == [r["df"] for r in everything.records[:2]]
    assert [r["df"] for r in second.records] == [r["df"] for r in everything.records[2:4]]


def test_total_hits_is_not_capped_by_the_page(search):
    result = search.search("Åbo", limit=1)
    assert len(result.records) == 1
    assert result.total_hits > 1


def test_language_filter(search):
    result = search.search("Åbo", limit=100, language="latina")
    assert result.records
    assert {rec["language"] for rec in result.records} == {"latina"}


def test_issuingplace_filter_is_case_insensitive(search):
    result = search.search("Åbo", limit=100, issuingplace="åbo")
    assert result.records
    assert all(rec["issuingplace"] == "Åbo" for rec in result.records)


def test_country_filter(search):
    # match_all=False because these are alternatives, not co-occurring terms.
    result = search.search("Perugia Lateranen", limit=100, country="Italia", match_all=False)
    assert result.records
    assert all(rec["issuingplacecountry"] == "Italia" for rec in result.records)


def test_year_filter_matches_inside_a_closed_interval(search):
    """DF 1031 is dated 1443-1445; a search bounded to 1444 must find it."""
    result = search.search("Raseborg", limit=100, year_min=1444, year_max=1444)
    assert [rec["df"] for rec in result.records] == ["1031"]


def test_year_filter_excludes_outside_the_interval(search):
    assert search.search("Raseborg", limit=100, year_min=1500).total_hits == 0


def test_year_filter_keeps_open_ended_charters(search):
    """6,843 of 6,876 charters have no end year.

    Filtering on `dating_end_year` would drop essentially all of them; the
    derived interval must not.
    """
    result = search.search("Åbo", limit=100, year_min=1300, year_max=1400)
    assert result.records
    assert any(rec["dating_end_year"] is None for rec in result.records)


def test_inverted_year_range_returns_nothing(search):
    """An inverted range is unsatisfiable — the MCP layer rejects it up front."""
    assert search.search("Åbo", year_min=1500, year_max=1300).total_hits == 0


def test_get_charter_by_df_number(search):
    charter = search.get_charter(1031)
    assert charter is not None
    assert charter["df"] == "1031"
    assert charter["year_from"] == 1443


def test_get_charter_accepts_string(search):
    assert search.get_charter("1031")["df"] == "1031"


def test_get_charter_unknown_returns_none(search):
    assert search.get_charter(999999) is None


def test_get_charter_non_numeric_returns_none(search):
    assert search.get_charter("DF 1031") is None


def test_results_omit_the_full_text_column(search):
    """searchable_text just repeats other columns; every search fetches up to
    10,000 rows to count them, so carrying it doubles the payload for nothing."""
    result = search.search("Åbo")
    assert "searchable_text" not in result.records[0]
    assert "transcript" in result.records[0]


def test_get_charter_returns_the_same_shape_as_a_search_hit(search):
    hit = search.search("Raseborg", limit=1).records[0]
    charter = search.get_charter(hit["df"])
    assert charter is not None
    assert set(charter) - {"_score", "_rowid"} == set(hit) - {"_score", "_rowid"}


def test_total_is_flagged_when_it_hits_the_cap(search, monkeypatch):
    """Past the cap, total_hits is a floor — the formatter must not print it bare."""
    from ra_mcp_kansallisarkisto_lib import dataset

    monkeypatch.setattr(dataset, "MAX_TOTAL_COUNT", 2)
    result = search.search("Åbo", limit=2)
    assert result.total_hits == 2
    assert result.total_is_capped is True


def test_total_is_not_flagged_below_the_cap(search):
    assert search.search("Åbo", limit=1).total_is_capped is False
