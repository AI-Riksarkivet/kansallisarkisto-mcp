"""Tests for DfRecord — the source-JSON conventions it has to normalise."""

from ra_mcp_kansallisarkisto_lib.models import DfRecord, VoudintilitRecord


def test_unknown_year_zero_becomes_none():
    """0 in a year field means 'unknown', not year 0, and must not survive as a value."""
    record = DfRecord.from_json({"objectID": "x", "df": "1", "dating_start_year": 0, "dating_end_year": 0})
    assert record.dating_start_year is None
    assert record.dating_end_year is None
    assert record.year_from is None
    assert record.year_to is None


def test_open_ended_dating_closes_to_start_year():
    """A charter with a start year and no end year is dated to that single year."""
    record = DfRecord.from_json({"objectID": "x", "df": "526", "dating_start_year": 1347, "dating_end_year": 0})
    assert record.dating_end_year is None
    assert (record.year_from, record.year_to) == (1347, 1347)


def test_closed_dating_interval_preserved():
    record = DfRecord.from_json({"objectID": "x", "df": "1031", "dating_start_year": 1443, "dating_end_year": 1445})
    assert (record.year_from, record.year_to) == (1443, 1445)


def test_geoloc_is_flattened():
    record = DfRecord.from_json({"objectID": "x", "df": "1", "_geoloc": {"lat": 60.45, "lng": 22.27}})
    assert (record.lat, record.lng) == (60.45, 22.27)


def test_missing_geoloc_gives_null_pair():
    record = DfRecord.from_json({"objectID": "x", "df": "1", "_geoloc": {"lat": None, "lng": None}})
    assert record.lat is None
    assert record.lng is None


def test_df_number_parsed_for_ordering():
    assert DfRecord.from_json({"objectID": "x", "df": "1031"}).df_number == 1031


def test_searchable_text_covers_untranscribed_records():
    """36% of df has no transcript; the catalogue fields keep those searchable."""
    record = DfRecord.from_json(
        {
            "objectID": "x",
            "df": "670",
            "transcript": "",
            "issuingplace": "Åbo",
            "issuingplacecountry": "Suomi",
            "indexterm": "Piispat, Asiakirjat",
            "language": "latina",
        }
    )
    text = record.searchable_text
    assert "Åbo" in text
    assert "Piispat" in text
    assert text.strip()


def test_malformed_geoloc_does_not_raise_an_uncatchable_error():
    """The ingest skips a bad line by catching ValueError/TypeError.

    An AttributeError from a `_geoloc` that is a string rather than an object
    would escape that handler and abort the whole run over one record.
    """
    for bad in ("oops", [1, 2], 5):
        record = DfRecord.from_json({"objectID": "x", "df": "1", "_geoloc": bad})
        assert record.lat is None
        assert record.lng is None


def test_a_year_that_parses_to_zero_is_still_unknown():
    """0 means "unknown" whatever type it arrives as. The corpus only ever sends
    ints, but the harvest is re-runnable and the sibling corpora differ in field
    types — voudintilit's file_id is a zero-padded string where tuomiokirjat's is
    an int — so the defensive path exists and should be pinned."""
    from ra_mcp_kansallisarkisto_lib.models import _year

    for value in (0, "0", "00", " 0 ", 0.0):
        assert _year(value) is None, f"{value!r} should read as unknown"


def test_unparseable_years_are_unknown_rather_than_an_error():
    from ra_mcp_kansallisarkisto_lib.models import _year

    for value in ("", "n.d.", None, "circa 1400"):
        assert _year(value) is None


# --- voudintilit: one page of a bailiff's account book --------------------------

# Shaped like the real page 1578628789_0016 and its volume's Astia snapshot line; the
# file ids are illustrative.
VOLUME = {
    "volume_id": 1578628789,
    "reference": "2372",
    "title": "Ylä-Satakunnan tilikirja",
    "dates": "xx.xx.1585-xx.xx.1585",
    "fonds": "Satakunnan voutikuntien tilejä",
    "series": "Asiakirjat",
    "files": {15: "8489049754", 16: "8489049755"},
}
PAGE = {
    "objectID": "1578628789_0016",
    "alkuvuosi": 1585,
    "loppuvuosi": 1585,
    "arkistoyksikkö": "Ylä-Satakunnan tilikirja",
    "ay_id": 1578628789,
    "file_id": "0016",
    "teksti": "Bödich Fincke\nHaffwer Konung Matt gunsteligen förlänth",
    "aineistokokonaisuus": "Satakunnan voutikuntien tilejä",
}


def test_voudintilit_page_number_comes_from_the_zero_padded_file_id():
    record = VoudintilitRecord.from_json(PAGE, VOLUME)
    assert (record.page_id, record.volume_id, record.page, record.file_id) == ("1578628789_0016", 1578628789, 16, "0016")


def test_voudintilit_page_links_to_its_image_in_astia():
    record = VoudintilitRecord.from_json(PAGE, VOLUME)
    assert record.url == "https://astia.narc.fi/uusiastia/viewer/?fileId=8489049755&aineistoId=1578628789"
    assert (record.reference, record.series) == ("2372", "Asiakirjat")


def test_voudintilit_page_without_an_astia_volume_has_no_link_or_reference():
    record = VoudintilitRecord.from_json(PAGE, None)
    assert (record.url, record.reference) == ("", "")


def test_voudintilit_page_missing_from_astias_image_list_has_no_link():
    """Astia and Sisältöhaku disagree on some volumes' pages; the reference still holds."""
    record = VoudintilitRecord.from_json({**PAGE, "file_id": "0017", "objectID": "1578628789_0017"}, VOLUME)
    assert (record.url, record.reference) == ("", "2372")


def test_voudintilit_unknown_years_become_none():
    """66 pages, all in the Satakunta catalogue volume, carry 0 for both years."""
    record = VoudintilitRecord.from_json({**PAGE, "alkuvuosi": 0, "loppuvuosi": 0}, VOLUME)
    assert (record.year_start, record.year_end, record.year_from, record.year_to) == (None, None, None, None)


def test_voudintilit_inverted_years_keep_the_start_year():
    """27 pages in one volume say 1615–1516. The end precedes the corpus (1539), so it
    is the typo; widening to 1516–1615 would put them in every century's results."""
    record = VoudintilitRecord.from_json({**PAGE, "alkuvuosi": 1615, "loppuvuosi": 1516}, VOLUME)
    assert (record.year_start, record.year_end) == (1615, 1516)
    assert (record.year_from, record.year_to) == (1615, 1615)


def test_voudintilit_untitled_volume_takes_astias_title():
    """The export leaves the catalogue volume untitled; Astia names it."""
    record = VoudintilitRecord.from_json({**PAGE, "arkistoyksikkö": ""}, {**VOLUME, "title": "Satakunnan voudintilien arkistoluettelo"})
    assert record.account_book == "Satakunnan voudintilien arkistoluettelo"


def test_voudintilit_searchable_text_matches_what_sisaltohaku_searches():
    """Sisältöhaku's own search attributes for this corpus: text, account book, collection."""
    text = VoudintilitRecord.from_json(PAGE, VOLUME).searchable_text
    for part in ("Bödich Fincke", "Ylä-Satakunnan tilikirja", "Satakunnan voutikuntien tilejä"):
        assert part in text


def test_voudintilit_malformed_page_number_is_not_an_uncatchable_error():
    record = VoudintilitRecord.from_json({**PAGE, "file_id": "x"}, VOLUME)
    assert (record.page, record.url) == (None, "")
