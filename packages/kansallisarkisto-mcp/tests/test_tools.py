"""Tools exercised through an in-memory MCP client, as a real client calls them."""

from __future__ import annotations

import inspect

import pytest
from fastmcp import Client
from fastmcp.tools import FunctionTool

from ra_mcp_kansallisarkisto_mcp import tools


@pytest.fixture(autouse=True)
def reset_search():
    yield
    tools._search = None


async def call(tool: str, args: dict) -> str:
    async with Client(tools.kansallisarkisto_mcp) as client:
        result = await client.call_tool(tool, args)
    return result.content[0].text


async def test_both_tools_are_registered():
    async with Client(tools.kansallisarkisto_mcp) as client:
        assert {t.name for t in await client.list_tools()} == {"df_search", "df_get_charter"}


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


@pytest.mark.parametrize("name", ["df_search", "df_get_charter"])
async def test_tool_handlers_are_sync_so_they_do_not_block_the_event_loop(name):
    """FastMCP runs a coroutine tool inline but dispatches a sync one to a thread.

    LanceDB's API is blocking, so a coroutine handler would stall every other
    in-flight request for the length of a search.
    """
    tool = await tools.kansallisarkisto_mcp.get_tool(name)
    assert isinstance(tool, FunctionTool)
    assert not inspect.iscoroutinefunction(tool.fn), f"{name} must be a sync def"
