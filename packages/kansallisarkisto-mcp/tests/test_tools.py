"""Tools exercised through an in-memory MCP client, as a real client calls them."""

from __future__ import annotations

import inspect
import json
import logging

import pytest
from fastmcp import Client
from fastmcp.tools import FunctionTool

from ra_mcp_kansallisarkisto_mcp import tools

TOOLS = ("df_search", "df_get_charter", "voudintilit_search", "voudintilit_get_page", "tuomiokirjat_search", "tuomiokirjat_get_page")


@pytest.fixture(autouse=True)
def reset_search():
    yield
    tools._search = None
    tools._voudintilit_search = None
    tools._tuomiokirjat_search = None


async def call(tool: str, args: dict) -> str:
    async with Client(tools.kansallisarkisto_mcp) as client:
        result = await client.call_tool(tool, args)
    return result.content[0].text


async def test_every_tool_is_registered():
    async with Client(tools.kansallisarkisto_mcp) as client:
        assert {t.name for t in await client.list_tools()} == set(TOOLS)


async def test_search_returns_formatted_hits(df_search):
    tools._search = df_search
    out = await call("df_search", {"keyword": "konung"})
    assert "Diplomatarium Fennicum search results for 'konung'" in out
    assert "**DF " in out


async def test_search_marks_untranscribed_charters(df_search):
    """An empty transcript must read as 'not transcribed', not as an empty record."""
    tools._search = df_search
    out = await call("df_search", {"keyword": "Åbo", "limit": 100})
    assert "catalogued but not transcribed" in out


async def test_search_filters_reach_the_query(df_search):
    tools._search = df_search
    out = await call("df_search", {"keyword": "Åbo", "limit": 100, "language": "latina"})
    assert "latina" in out
    assert "language: ruotsi" not in out


async def test_search_year_range_uses_interval_overlap(df_search):
    """DF 1031 is dated 1443-1445, so a search bounded to 1444 must return it."""
    tools._search = df_search
    out = await call("df_search", {"keyword": "Raseborg", "year_min": 1444, "year_max": 1444})
    assert "**DF 1031**" in out


async def test_empty_keyword_is_an_actionable_message_not_a_crash(df_search):
    tools._search = df_search
    out = await call("df_search", {"keyword": "   "})
    assert out.startswith("Error: keyword must not be empty")


async def test_inverted_year_range_is_reported_rather_than_silently_empty(df_search):
    """An inverted range matches nothing; saying 'no results' would hide the swap."""
    tools._search = df_search
    out = await call("df_search", {"keyword": "Åbo", "year_min": 1500, "year_max": 1300})
    assert "inverted" in out


async def test_missing_table_is_reported_as_text(monkeypatch, tmp_path):
    """The image ships without data; the tools must say so instead of crashing."""
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    out = await call("df_search", {"keyword": "konung"})
    assert "df table is not available" in out


async def test_get_charter_returns_the_full_transcript(df_search):
    tools._search = df_search
    out = await call("df_get_charter", {"df_number": 526})
    assert "**DF 526**" in out
    assert "Transcript:" in out


async def test_get_charter_unknown_number(df_search):
    tools._search = df_search
    out = await call("df_get_charter", {"df_number": 999999})
    assert "No charter DF 999999" in out


async def test_search_errors_are_returned_as_text(df_search, monkeypatch):
    """A raised exception reaches the model as a protocol error it cannot act on."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("lance exploded: /data/df.lance/_versions/3.manifest")

    monkeypatch.setattr(df_search, "search", boom)
    tools._search = df_search
    out = await call("df_search", {"keyword": "konung"})
    assert out.startswith("Error: the search failed with an internal RuntimeError")
    # The message can name server paths; it stays in the log, not in the reply.
    assert "/data/df.lance" not in out


@pytest.mark.parametrize("name", TOOLS)
async def test_tool_handlers_are_sync_so_they_do_not_block_the_event_loop(name):
    """FastMCP runs a coroutine tool inline but dispatches a sync one to a thread.

    LanceDB's API is blocking, so a coroutine handler would stall every other
    in-flight request for the length of a search.
    """
    tool = await tools.kansallisarkisto_mcp.get_tool(name)
    assert isinstance(tool, FunctionTool)
    assert not inspect.iscoroutinefunction(tool.fn), f"{name} must be a sync def"


async def test_caller_correctable_errors_keep_their_message(df_search):
    """A SearchInputError is written for the caller, so its sentence is the reply."""
    tools._search = df_search
    out = await call("df_search", {"keyword": '"de ecclesia"', "fuzzy": 1})
    assert out.startswith("Error: fuzzy=1 cannot be combined with a quoted phrase")


async def test_a_lancedb_valueerror_does_not_reach_the_client(df_search):
    """lancedb raises ValueError too, and its messages quote dataset paths and
    internal query structure. Catching the base class rather than
    SearchInputError handed those straight to a public HTTP client — an
    out-of-int32 year_min was enough to leak the filter expression.
    """
    tools._search = df_search
    out = await call("df_search", {"keyword": "Åbo", "year_min": 10**20})
    assert out.startswith("Error: the search failed with an internal ")
    assert "year_to >=" not in out
    assert "Float64" not in out


async def test_a_prefix_reaches_a_charter_no_stem_or_fuzzy_could(df_search):
    """DF 173 says 'leprosorum' and 'Reualie', has no recorded place, and was
    invisible to 'lepros' at any fuzziness and to issuingplace='Tallinn'."""
    tools._search = df_search
    out = await call("df_search", {"keyword": "lepros* reval*|reual*|revel*|reuel*|reffl*"})
    assert "**DF 173**" in out
    assert "showing 1 of 1" in out


async def test_a_place_filter_reports_what_it_leaves_out_even_when_empty(df_search):
    tools._search = df_search
    out = await call("df_search", {"keyword": "leprosorum", "issuingplace": "Tallinn"})
    assert out.startswith("No Diplomatarium Fennicum results found")
    assert "Note: issuingplace='Tallinn' matches the recorded place of ISSUE only" in out
    assert "reval*|reual*" in out


async def test_a_bad_prefix_is_an_actionable_message_not_a_crash(df_search):
    tools._search = df_search
    out = await call("df_search", {"keyword": "ab*"})
    assert out.startswith("Error: 'ab*': a prefix needs at least 3 characters")


async def test_prefix_search_and_the_place_trap_are_in_the_tool_description():
    """The description is the only place a model learns either; nothing else
    tests prose."""
    async with Client(tools.kansallisarkisto_mcp) as client:
        df_search = next(t for t in await client.list_tools() if t.name == "df_search")
    assert "lepros*" in df_search.description
    assert "ISSUED" in df_search.description
    schema = json.dumps(df_search.inputSchema)
    assert "trailing *" in schema
    assert "reval*|reual*" in schema


# --- voudintilit ----------------------------------------------------------------


async def test_voudintilit_search_cites_reference_book_year_and_page(voudintilit_search):
    tools._voudintilit_search = voudintilit_search
    out = await call("voudintilit_search", {"keyword": "konung"})
    assert "Voudintilit search results for 'konung'" in out
    assert "**2372 Ylä-Satakunnan tilikirja 1585, p. 16**" in out
    assert "https://astia.narc.fi/uusiastia/viewer/?fileId=8489049831&aineistoId=1578628789" in out


async def test_voudintilit_collection_is_a_fixed_choice():
    """The labels are Finnish genitives a free-text filter would miss, so the schema a
    client sees offers the two keys and nothing else."""
    tool = await tools.kansallisarkisto_mcp.get_tool("voudintilit_search")
    assert tool is not None
    schema = json.dumps(tool.parameters["properties"]["collection"])
    assert '"hame"' in schema
    assert '"satakunta"' in schema


async def test_instructions_cover_every_tool():
    """The server instructions are what a client reads before it calls anything; a tool
    they never mention is one a model will not think to reach for."""
    instructions = tools.kansallisarkisto_mcp.instructions or ""
    assert [name for name in TOOLS if name not in instructions] == []


async def test_voudintilit_filters_reach_the_query(voudintilit_search):
    tools._voudintilit_search = voudintilit_search
    out = await call("voudintilit_search", {"keyword": "smör", "collection": "hame", "limit": 100})
    assert "Hämeen linnan tilikirja" in out
    assert "Satakunnan voutikuntien tilejä" not in out


async def test_voudintilit_inverted_year_range_is_reported(voudintilit_search):
    tools._voudintilit_search = voudintilit_search
    out = await call("voudintilit_search", {"keyword": "smör", "year_min": 1600, "year_max": 1500})
    assert "inverted" in out


async def test_voudintilit_get_page_gives_the_text_link_and_neighbours(voudintilit_search):
    tools._voudintilit_search = voudintilit_search
    out = await call("voudintilit_get_page", {"page_id": "1578628789_0016"})
    assert "**2372 Ylä-Satakunnan tilikirja 1585, p. 16**" in out
    assert "Text:" in out
    assert "Bödich Fincke" in out
    assert "Previous page: 1578628789_0015" in out
    assert "Next page: 1578628789_0017" in out


async def test_voudintilit_get_page_unknown_id(voudintilit_search):
    tools._voudintilit_search = voudintilit_search
    out = await call("voudintilit_get_page", {"page_id": "1578628789_9999"})
    assert "No page 1578628789_9999" in out


async def test_voudintilit_get_page_answers_a_malformed_id(voudintilit_search):
    tools._voudintilit_search = voudintilit_search
    out = await call("voudintilit_get_page", {"page_id": "DF 1031"})
    assert "No page DF 1031" in out


async def test_voudintilit_get_page_reports_a_missing_table(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    out = await call("voudintilit_get_page", {"page_id": "1578628789_0016"})
    assert "voudintilit table is not available" in out


async def test_voudintilit_missing_table_is_reported_as_text(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    out = await call("voudintilit_search", {"keyword": "konung"})
    assert "voudintilit table is not available" in out


# --- tuomiokirjat ----------------------------------------------------------------


async def test_court_search_cites_series_signum_year_and_page(tuomiokirjat_search):
    tools._tuomiokirjat_search = tuomiokirjat_search
    out = await call("tuomiokirjat_search", {"keyword": "Larsson"})
    assert "Tuomiokirjat search results for 'Larsson'" in out
    assert "**Porin raastuvanoikeuden tuomiokirjat a:1 1622–1639, p. 66**" in out
    assert "https://astia.narc.fi/uusiastia/viewer/?fileId=5929607974&aineistoId=2317506414" in out


async def test_court_filters_reach_the_query(tuomiokirjat_search):
    tools._tuomiokirjat_search = tuomiokirjat_search
    out = await call("tuomiokirjat_search", {"keyword": "1817", "collection": "Lappeen", "limit": 100})
    assert "Lappeen tuomiokunnan renovoidut tuomiokirjat" in out
    assert "Helsingin" not in out
    out = await call("tuomiokirjat_search", {"keyword": "Maji", "series": "Helsingin", "year_min": 1790, "year_max": 1795, "limit": 100})
    assert "**Helsingin raastuvanoikeuden tuomiokirjat g:87 1792, p. 45**" in out


async def test_court_inverted_year_range_is_reported(tuomiokirjat_search):
    tools._tuomiokirjat_search = tuomiokirjat_search
    out = await call("tuomiokirjat_search", {"keyword": "Maji", "year_min": 1800, "year_max": 1700})
    assert "inverted" in out


async def test_court_get_page_gives_the_text_link_and_neighbours(tuomiokirjat_search):
    tools._tuomiokirjat_search = tuomiokirjat_search
    out = await call("tuomiokirjat_get_page", {"page_id": "Y4Q4IZcBCao99UPKS6L8"})
    assert "**Helsingin raastuvanoikeuden tuomiokirjat g:87 1792, p. 45**" in out
    assert "Text:" in out
    assert "Ehronen i Kraft" in out
    assert "Previous page: kIQ4IZcBCao99UPKTaIn" in out
    assert "Next page: I4Q4IZcBCao99UPKSqJT" in out


async def test_court_get_page_unknown_id(tuomiokirjat_search):
    tools._tuomiokirjat_search = tuomiokirjat_search
    out = await call("tuomiokirjat_get_page", {"page_id": "nonsense"})
    assert "No page nonsense in tuomiokirjat" in out


async def test_court_prefix_search_is_refused_with_advice(tuomiokirjat_search, monkeypatch):
    """7.7M pages are far past the vocabulary cap; the refusal must say what to do instead."""
    from ra_mcp_kansallisarkisto_lib import dataset

    monkeypatch.setattr(dataset, "MAX_VOCABULARY_ROWS", 1)
    tools._tuomiokirjat_search = tuomiokirjat_search
    out = await call("tuomiokirjat_search", {"keyword": "Lars*"})
    assert out.startswith("Error: prefix search")
    assert "bref|breff" in out and "fuzzy=1" in out


# --- what an operator sees per call ------------------------------------------
#
# The Space runs without OTel, so the log is the only signal there — and until
# now it showed "Processing request of type CallToolRequest" and nothing else.
# Every tool now logs one line: which tool, what it was asked, what came of it,
# and how long it took.

LOG = "ra_mcp_kansallisarkisto_mcp.errors"


async def test_every_search_logs_what_it_was_asked_and_what_it_found(caplog, df_search, voudintilit_search, tuomiokirjat_search):
    tools._search, tools._voudintilit_search, tools._tuomiokirjat_search = df_search, voudintilit_search, tuomiokirjat_search
    with caplog.at_level(logging.INFO, logger=LOG):
        await call("df_search", {"keyword": "Raseborg", "year_min": 1444, "year_max": 1444})
        await call("voudintilit_search", {"keyword": "smör", "collection": "hame"})
        await call("tuomiokirjat_search", {"keyword": "Larsson", "series": "Porin"})
    lines = [r.getMessage() for r in caplog.records if r.name == LOG]
    assert len(lines) == 3
    assert "df_search keyword='Raseborg' year_min=1444 year_max=1444 -> 1 hit" in lines[0]
    assert "voudintilit_search keyword='smör' collection='hame' ->" in lines[1] and "hits" in lines[1]
    assert "tuomiokirjat_search keyword='Larsson' series='Porin' ->" in lines[2]
    assert all(" ms" in line for line in lines)


async def test_unset_filters_are_not_logged(caplog, df_search):
    """A line of 'language=None issuingplace=None …' on every call is noise."""
    tools._search = df_search
    with caplog.at_level(logging.INFO, logger=LOG):
        await call("df_search", {"keyword": "Raseborg"})
    line = next(r.getMessage() for r in caplog.records if r.name == LOG)
    assert "None" not in line


async def test_page_lookups_log_found_or_not(caplog, df_search, tuomiokirjat_search):
    tools._search, tools._tuomiokirjat_search = df_search, tuomiokirjat_search
    with caplog.at_level(logging.INFO, logger=LOG):
        await call("df_get_charter", {"df_number": 526})
        await call("df_get_charter", {"df_number": 999999})
        await call("tuomiokirjat_get_page", {"page_id": "Y4Q4IZcBCao99UPKS6L8"})
    lines = [r.getMessage() for r in caplog.records if r.name == LOG]
    assert "df_get_charter df_number=526 -> found" in lines[0]
    assert "df_get_charter df_number=999999 -> not found" in lines[1]
    assert "tuomiokirjat_get_page page_id='Y4Q4IZcBCao99UPKS6L8' -> found" in lines[2]


async def test_failures_are_logged_with_their_kind(caplog, df_search, monkeypatch, tmp_path):
    tools._search = df_search
    with caplog.at_level(logging.INFO, logger=LOG):
        await call("df_search", {"keyword": '"de ecclesia"', "fuzzy": 1})
    assert "df_search" in caplog.text and "-> validation: fuzzy=1 cannot be combined" in caplog.text

    def boom(*_args, **_kwargs):
        raise RuntimeError("lance exploded: /data/df.lance/_versions/3.manifest")

    monkeypatch.setattr(df_search, "search", boom)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=LOG):
        await call("df_search", {"keyword": "konung"})
    line = next(r.getMessage() for r in caplog.records if r.name == LOG and r.levelno == logging.INFO)
    assert "df_search keyword='konung' -> RuntimeError" in line

    tools._search = None
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=LOG):
        await call("df_search", {"keyword": "konung"})
    assert "df_search keyword='konung' -> missing table" in caplog.text


async def test_research_context_is_accepted_and_logged(caplog, df_search, voudintilit_search, tuomiokirjat_search):
    """ra-mcp's tools take research_context, so clients send it here too — and the
    whole call was being rejected as an unexpected argument. It is the 'why' behind
    a query, worth a place in the log."""
    tools._search, tools._voudintilit_search, tools._tuomiokirjat_search = df_search, voudintilit_search, tuomiokirjat_search
    with caplog.at_level(logging.INFO, logger=LOG):
        out = await call("df_search", {"keyword": "Raseborg", "research_context": "Raseborg castle's garrison"})
        await call("voudintilit_search", {"keyword": "smör", "research_context": "butter tithes"})
        await call("tuomiokirjat_search", {"keyword": "Larsson", "research_context": "a Pori burgher"})
    assert "Diplomatarium Fennicum search results" in out
    assert 'research_context="Raseborg castle\'s garrison"' in caplog.text
    assert "research_context='butter tithes'" in caplog.text
    assert "research_context='a Pori burgher'" in caplog.text


async def test_court_missing_table_is_reported_as_text(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    assert "tuomiokirjat table is not available" in await call("tuomiokirjat_search", {"keyword": "Larsson"})
    assert "tuomiokirjat table is not available" in await call("tuomiokirjat_get_page", {"page_id": "Y4Q4IZcBCao99UPKS6L8"})
