"""How a charter is rendered — the parts a reader has to be able to trust."""

from __future__ import annotations

from ra_mcp_kansallisarkisto_lib.dataset import SearchResult
from ra_mcp_kansallisarkisto_mcp.formatter import SNIPPET_CHARS, format_charter, format_error, format_search_results


def charter(**overrides):
    base = {
        "df": "526",
        "transcript": "Konung Magnus stadfäster …",
        "indexterm": "Paikallishallinto, Asiakirjat",
        "issuingplace": "Åbo",
        "issuingplacecountry": "Suomi",
        "language": "ruotsi",
        "dating_start_year": 1347,
        "dating_end_year": None,
        "lat": 60.45,
        "lng": 22.27,
    }
    return {**base, **overrides}


def results(*records):
    return SearchResult(records=list(records), total_hits=len(records), keyword="konung", offset=0, limit=25)


def test_hit_leads_with_the_df_number():
    """The DF number is the citable identifier — it has to be impossible to miss."""
    assert "**DF 526**" in format_search_results(results(charter()))


def test_single_year_dating_is_not_rendered_as_a_range():
    """6,843 of 6,876 charters have no end year; showing '1347–0' would be a lie."""
    out = format_search_results(results(charter()))
    assert "1347" in out
    assert "1347–" not in out


def test_closed_interval_is_rendered_as_a_range():
    assert "1443–1445" in format_search_results(results(charter(dating_start_year=1443, dating_end_year=1445)))


def test_undated_charter_says_so():
    assert "undated" in format_search_results(results(charter(dating_start_year=None, dating_end_year=None)))


def test_missing_place_is_named_rather_than_left_blank():
    out = format_search_results(results(charter(issuingplace="", issuingplacecountry="")))
    assert "place of issue unrecorded" in out


def test_untranscribed_charter_is_labelled():
    out = format_search_results(results(charter(transcript="")))
    assert "catalogued but not transcribed" in out


def test_long_transcripts_are_snipped_in_search_results():
    out = format_search_results(results(charter(transcript="ord " * 500)))
    assert "…" in out
    assert len(out) < SNIPPET_CHARS * 3


def test_full_charter_is_not_snipped():
    long_text = "ord " * 500
    out = format_charter(charter(transcript=long_text), 526)
    assert long_text.strip() in out


def test_full_charter_reports_coordinates_of_the_place_of_issue():
    out = format_charter(charter(), 526)
    assert "place of issue: 60.45, 22.27" in out


def test_full_charter_without_coordinates_omits_them():
    assert "Coordinates" not in format_charter(charter(lat=None, lng=None), 526)


def test_missing_charter():
    assert "No charter DF 9999" in format_charter(None, 9999)


def test_format_error_keeps_the_type_but_not_the_message():
    """The type tells a caller whether to retry; the message can name server paths."""
    out = format_error(ValueError("cannot open /data/df.lance"))
    assert "ValueError" in out
    assert "/data/df.lance" not in out
