"""Tests for the shared LanceDB spine: predicate builders and the result envelope."""

from ra_mcp_kansallisarkisto_lib.dataset import (
    SearchResult,
    at_least,
    combine,
    equals,
    format_results,
    require_keyword,
    require_ordered_range,
    text_contains,
)


def test_equals_quotes_strings_and_leaves_ints_bare():
    assert equals("language", "latina") == "language = 'latina'"
    assert equals("df_number", 1031) == "df_number = 1031"


def test_string_literals_escape_single_quotes():
    assert equals("issuingplace", "O'Neill") == "issuingplace = 'O''Neill'"


def test_text_contains_lowercases_and_escapes_wildcards():
    assert text_contains("issuingplace", "Åbo") == "lower(issuingplace) LIKE '%åbo%' ESCAPE '\\'"
    assert "\\%" in text_contains("indexterm", "100%")


def test_at_least():
    assert at_least("year_to", 1400) == "year_to >= 1400"


def test_combine_drops_unset_filters():
    assert combine(None, "a = 1", None, "b = 2") == "a = 1 AND b = 2"


def test_combine_returns_none_when_nothing_is_set():
    assert combine(None, None) is None


def test_require_keyword():
    assert require_keyword("konung", "'konung'") is None
    blank = require_keyword("  ", "'konung'")
    assert blank is not None and "must not be empty" in blank


def test_require_ordered_range():
    assert require_ordered_range(1300, 1400, "year") is None
    assert require_ordered_range(None, 1400, "year") is None
    swapped = require_ordered_range(1400, 1300, "year")
    assert swapped is not None and "inverted" in swapped


def _result(records: list[dict], *, total_hits: int | None = None, offset: int = 0, limit: int = 25, capped: bool = False) -> SearchResult:
    return SearchResult(
        records=records,
        total_hits=len(records) if total_hits is None else total_hits,
        keyword="konung",
        offset=offset,
        limit=limit,
        total_is_capped=capped,
    )


def _render(rec, lines):
    lines.append(f"DF {rec['df']}")


def test_format_results_renders_header_and_records():
    out = format_results(_result([{"df": "526"}]), label="Charter", render_record=_render)
    assert "showing 1 of 1 records (offset 0)" in out
    assert "DF 526" in out


def test_format_results_offers_the_next_page():
    out = format_results(_result([{"df": "526"}], total_hits=40, limit=25), label="Charter", render_record=_render)
    assert "offset=25" in out


def test_format_results_no_next_page_on_the_last_one():
    out = format_results(_result([{"df": "526"}], total_hits=26, offset=25, limit=25), label="Charter", render_record=_render)
    assert "More results" not in out


def test_format_results_empty():
    assert "No Charter results found" in format_results(_result([]), label="Charter", render_record=_render)


def test_format_results_past_the_end_reports_the_total():
    out = format_results(_result([], total_hits=3, offset=100), label="Charter", render_record=_render)
    assert "No more Charter results" in out
    assert "Total found: 3" in out


def test_table_names_returns_a_plain_sorted_list(db, df_table):
    """lancedb's list_tables() returns a paginated response object, not a list."""
    from ra_mcp_kansallisarkisto_lib.dataset import table_names

    assert table_names(db) == ["df"]


def test_format_results_reports_a_capped_total_as_a_floor():
    """Printing a capped 10,000 bare would claim it as the real number of matches."""
    out = format_results(_result([{"df": "526"}], total_hits=10000, capped=True), label="Charter", render_record=_render)
    assert "of 10000+ records" in out
