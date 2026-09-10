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


def test_voudintilit_alternatives_reach_both_spellings(voudintilit_search):
    """The spine's 'a|b' is what stands in for a prefix on a corpus too large for one."""
    found = _page_ids(voudintilit_search.search("Fincke|Nuksuma", limit=100))
    assert {"1578628789_0016", "1580560161_0001"} <= found


def test_voudintilit_capped_total_comes_with_advice(voudintilit_search, monkeypatch):
    """'smör' alone passes the 10,000 cap on the real table."""
    from ra_mcp_kansallisarkisto_lib import dataset

    monkeypatch.setattr(dataset, "MAX_TOTAL_COUNT", 1)
    capped = voudintilit_search.search("smör", limit=1)
    assert capped.total_is_capped
    assert any("collection" in note and "account_book" in note for note in capped.notes)
    assert voudintilit_search.search("zzzq", limit=1).notes == []


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


# --- tuomiokirjat ----------------------------------------------------------------

PORI_66 = "PpblIZcBCao99UPKvl9-"
HELSINKI_45 = "Y4Q4IZcBCao99UPKS6L8"


def test_court_search_finds_a_name(tuomiokirjat_search):
    assert PORI_66 in _page_ids(tuomiokirjat_search.search("Larsson", limit=100))


def test_court_search_returns_a_duplicated_image_once(tuomiokirjat_search):
    """The fixture holds the Lappee volume's first page under two ids."""
    result = tuomiokirjat_search.search("Förtekning", limit=100)
    assert [rec["page_id"] for rec in result.records] == ["eaYlI5cBCao99UPKZp70"]


def test_court_collection_filter_is_a_case_insensitive_substring(tuomiokirjat_search):
    result = tuomiokirjat_search.search("1817", limit=100, collection="lappeen tuomiokunnan")
    assert result.records
    assert {rec["collection"] for rec in result.records} == {"Lappeen tuomiokunnan renovoidut tuomiokirjat"}


def test_court_series_filter_is_a_case_insensitive_substring(tuomiokirjat_search):
    result = tuomiokirjat_search.search("och", limit=100, series="porin")
    assert result.records
    assert {rec["series"] for rec in result.records} == {"Porin raastuvanoikeuden tuomiokirjat"}


def test_court_inverted_years_filter_as_the_start_year(tuomiokirjat_search):
    """The Åland page reads 1899–1898."""
    assert "u8T7I5cBCao99UPKLKsq" in _page_ids(tuomiokirjat_search.search("Ahvenanmaa", limit=100, year_min=1899, year_max=1899))
    assert "u8T7I5cBCao99UPKLKsq" not in _page_ids(tuomiokirjat_search.search("Ahvenanmaa", limit=100, year_min=1898, year_max=1898))


def test_court_1984_page_filters_as_1895(tuomiokirjat_search):
    found = _page_ids(tuomiokirjat_search.search("Lagfartsprotokoll", limit=100, year_min=1890, year_max=1900))
    assert "uNJfJJcBCao99UPK2fWO" in found
    assert "uNJfJJcBCao99UPK2fWO" not in _page_ids(tuomiokirjat_search.search("Lagfartsprotokoll", limit=100, year_min=1980))


def test_court_undated_page_is_left_out_by_a_year_filter(tuomiokirjat_search):
    assert "314155174_0002" in _page_ids(tuomiokirjat_search.search("Sälljärvi", limit=100))
    assert "314155174_0002" not in _page_ids(tuomiokirjat_search.search("Sälljärvi", limit=100, year_min=1600))


def test_court_alternatives_go_through_the_text_index(tuomiokirjat_search):
    """The expanded boolean query has to be built on the column the index is on."""
    assert {PORI_66, HELSINKI_45} <= _page_ids(tuomiokirjat_search.search("Larsson|Ehronen", limit=100))


def test_court_capped_total_comes_with_advice(tuomiokirjat_search, monkeypatch):
    """On 7.8M pages most common words pass the cap. A bare '10000+' tells the caller
    nothing about what to do; the note says how to make the total mean something."""
    from ra_mcp_kansallisarkisto_lib import dataset

    monkeypatch.setattr(dataset, "MAX_TOTAL_COUNT", 1)
    capped = tuomiokirjat_search.search("1817", limit=1)
    assert capped.total_is_capped
    assert any("collection" in note and "series" in note for note in capped.notes)
    # With the cap at 1 every hit is a capped result; only a miss is not.
    assert tuomiokirjat_search.search("zzzq", limit=1).notes == []


def test_court_results_carry_the_text(tuomiokirjat_search):
    record = tuomiokirjat_search.search("Larsson").records[0]
    assert record["text"].startswith("Erich Larsson")
    assert "searchable_text" not in record


def test_court_get_page_by_id(tuomiokirjat_search):
    page = tuomiokirjat_search.get_page(HELSINKI_45)
    assert page is not None
    assert (page["page"], page["reference"], page["series"]) == (45, "g:87", "Helsingin raastuvanoikeuden tuomiokirjat")
    assert page["url"] == "https://astia.narc.fi/uusiastia/viewer/?fileId=5930213631&aineistoId=2320246345"


def test_court_get_page_names_its_neighbours(tuomiokirjat_search):
    page = tuomiokirjat_search.get_page(HELSINKI_45)
    assert (page["previous_page_id"], page["next_page_id"]) == ("kIQ4IZcBCao99UPKTaIn", "I4Q4IZcBCao99UPKSqJT")


def test_court_get_page_has_no_neighbour_beyond_the_corpus(tuomiokirjat_search):
    """Pori page 65 is the volume's first page in the fixture."""
    page = tuomiokirjat_search.get_page("V5blIZcBCao99UPKv18e")
    assert (page["previous_page_id"], page["next_page_id"]) == (None, PORI_66)


def test_court_get_page_of_an_empty_page(tuomiokirjat_search):
    page = tuomiokirjat_search.get_page("kHjAIJcBCao99UPKuj1F")
    assert page is not None
    assert page["text"] == ""


def test_court_get_page_quotes_its_id_safely(tuomiokirjat_search):
    """The id is the one caller-supplied string that reaches a predicate."""
    for page_id in ("x'y", "abc\\", "' OR 1=1 --", "abc\\' OR page_id != '"):
        assert tuomiokirjat_search.get_page(page_id) is None, page_id


def test_court_get_page_without_a_page_number_has_no_neighbours(db, tmp_path, tuomiokirjat_fixture, tuomiokirjat_astia_fixture):
    """A page whose number did not parse cannot be placed in its volume; asking for its
    neighbours must answer 'none', not fail."""
    import json

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_tuomiokirjat
    from ra_mcp_kansallisarkisto_lib.search_operations import TuomiokirjatSearch

    rows = [json.loads(line) for line in tuomiokirjat_fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.append({**rows[0], "objectID": "unnumbered", "file_id": "kansi"})
    export = tmp_path / "export.jsonl"
    export.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    ingest_tuomiokirjat(db, export, tuomiokirjat_astia_fixture)
    page = TuomiokirjatSearch(db).get_page("unnumbered")
    assert page is not None
    assert (page["page"], page["previous_page_id"], page["next_page_id"]) == (None, None, None)


def test_court_get_page_unknown_or_dropped_returns_none(tuomiokirjat_search):
    # The second id of the duplicated Lappee page was dropped at ingest.
    for page_id in ("16YlI5cBCao99UPKgKEG", "nonsense", "", "x" * 5000):
        assert tuomiokirjat_search.get_page(page_id) is None, page_id


def test_court_get_page_returns_the_same_shape_as_a_search_hit(tuomiokirjat_search):
    hit = tuomiokirjat_search.search("Larsson", limit=1).records[0]
    page = tuomiokirjat_search.get_page(hit["page_id"])
    assert set(page) - {"_score", "_rowid", "previous_page_id", "next_page_id"} == set(hit) - {"_score", "_rowid"}


def test_issuingplace_filter_says_what_it_leaves_out(search):
    """A third of the corpus records no place; a filtered search must not read as
    complete. For the catalogue's modern names the note gives the period forms."""
    assert search.search("Åbo", limit=1).notes == []
    tallinn = search.search("Åbo", limit=1, issuingplace="Tallinn").notes
    assert len(tallinn) == 1
    assert "place of ISSUE" in tallinn[0]
    assert "reval*|reual*" in tallinn[0]
    generic = search.search("Åbo", limit=1, issuingplace="Åbo").notes
    assert len(generic) == 1
    assert "trailing *" in generic[0]
