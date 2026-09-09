"""Tests for DfRecord — the source-JSON conventions it has to normalise."""

from ra_mcp_kansallisarkisto_lib.models import DfRecord


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
