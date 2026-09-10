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


def test_input_guards_raise_search_input_error(search):
    """The MCP layer returns these messages verbatim, so they must be
    distinguishable from an arbitrary ValueError out of lancedb."""
    from ra_mcp_kansallisarkisto_lib.dataset import SearchInputError

    for kwargs in ({"keyword": ""}, {"keyword": "Åbo", "offset": -1}, {"keyword": "Åbo", "limit": 0}, {"keyword": '"de ecclesia"', "fuzzy": 1}):
        keyword = kwargs.pop("keyword")
        with pytest.raises(SearchInputError):
            search.search(keyword, **kwargs)


def test_a_lancedb_error_is_not_a_search_input_error(search):
    """An out-of-int32 bound is rejected by lancedb, not by our guards — so it
    must NOT arrive as the type whose message the MCP layer shows the caller."""
    from ra_mcp_kansallisarkisto_lib.dataset import SearchInputError

    with pytest.raises(ValueError) as excinfo:
        search.search("Åbo", year_min=10**20)
    assert not isinstance(excinfo.value, SearchInputError)


# --- voudintilit ----------------------------------------------------------------


def _page_ids(result) -> set[str]:
    return {rec["page_id"] for rec in result.records}


def test_voudintilit_search_finds_period_spelling(voudintilit_search):
    assert "1578628789_0016" in _page_ids(voudintilit_search.search("konung", limit=100))


def test_voudintilit_collection_filter_keeps_one_bailiwick(voudintilit_search):
    hame = voudintilit_search.search("smör", limit=100, collection="hame")
    satakunta = voudintilit_search.search("smör", limit=100, collection="satakunta")
    assert "1570685252_0014" in _page_ids(hame)
    assert {rec["collection"] for rec in hame.records} == {"Hämeen voutikuntien tilejä"}
    assert "1576084083_0017" in _page_ids(satakunta)
    assert "1570685252_0014" not in _page_ids(satakunta)


def test_voudintilit_unknown_collection_is_a_caller_error(voudintilit_search):
    """The labels are Finnish genitives, so the filter is a fixed choice — and a value
    outside it must say so, not quietly match nothing."""
    from ra_mcp_kansallisarkisto_lib.dataset import SearchInputError

    with pytest.raises(SearchInputError):
        voudintilit_search.search("smör", collection="uusimaa")


def test_voudintilit_account_book_filter_is_a_case_insensitive_substring(voudintilit_search):
    result = voudintilit_search.search("smör", limit=100, account_book="hämeen linnan")
    assert result.records
    assert {rec["volume_id"] for rec in result.records} == {1570685252}


def test_voudintilit_inverted_volume_counts_as_its_start_year(voudintilit_search):
    """1579931388 reads 1615–1516. Treated as a span it would match any year between."""
    assert "1579931388_0003" in _page_ids(voudintilit_search.search("Matzsons", limit=100, year_min=1610, year_max=1620))
    assert "1579931388_0003" not in _page_ids(voudintilit_search.search("Matzsons", limit=100, year_min=1520, year_max=1530))


def test_voudintilit_undated_catalogue_is_left_out_by_a_year_filter(voudintilit_search):
    assert "1580560161_0001" in _page_ids(voudintilit_search.search("Nuksuma", limit=100))
    assert "1580560161_0001" not in _page_ids(voudintilit_search.search("Nuksuma", limit=100, year_min=1500))


def test_voudintilit_empty_page_is_findable_by_its_account_book(voudintilit_search):
    assert "1576084083_0001" in _page_ids(voudintilit_search.search("tilikirja", limit=100))


def test_voudintilit_results_omit_the_full_text_column(voudintilit_search):
    record = voudintilit_search.search("konung").records[0]
    assert "searchable_text" not in record
    assert "text" in record


def test_voudintilit_get_page_by_id(voudintilit_search):
    page = voudintilit_search.get_page("1578628789_0016")
    assert page is not None
    assert (page["page"], page["reference"]) == (16, "2372")
    assert page["url"].endswith("fileId=8489049831&aineistoId=1578628789")


def test_voudintilit_get_page_names_its_neighbours(voudintilit_search):
    page = voudintilit_search.get_page("1578628789_0016")
    assert (page["previous_page_id"], page["next_page_id"]) == ("1578628789_0015", "1578628789_0017")


def test_voudintilit_neighbours_skip_a_page_gap(voudintilit_search):
    """1576091152 has no page 2; page 3's previous page is page 1."""
    assert voudintilit_search.get_page("1576091152_0003")["previous_page_id"] == "1576091152_0001"
    assert voudintilit_search.get_page("1576091152_0001")["previous_page_id"] is None


def test_voudintilit_get_page_unknown_or_malformed_returns_none(voudintilit_search):
    for page_id in ("1578628789_9999", "nonsense", "1578628789", "", "99999999999999999999_0001"):
        assert voudintilit_search.get_page(page_id) is None, page_id


def test_voudintilit_get_page_rejects_an_absurdly_long_id(voudintilit_search):
    """int() refuses strings past 4,300 digits; that has to read as 'no such page', not
    as an internal error with a traceback in the log."""
    assert voudintilit_search.get_page("1" * 5000 + "_0016") is None


def test_voudintilit_get_page_returns_the_same_shape_as_a_search_hit(voudintilit_search):
    hit = voudintilit_search.search("konung", limit=1).records[0]
    page = voudintilit_search.get_page(hit["page_id"])
    assert set(page) - {"_score", "_rowid", "previous_page_id", "next_page_id"} == set(hit) - {"_score", "_rowid"}
