"""The non-MCP HTTP routes: the landing page at / and the health probe."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from ra_mcp_kansallisarkisto_mcp.tools import kansallisarkisto_mcp

DF_FIXTURE = Path(__file__).parents[2] / "kansallisarkisto-lib" / "tests" / "fixtures" / "df_sample.jsonl"


@pytest.fixture(scope="module")
def client():
    """A sync facade over the ASGI app — the routes under test need no lifespan."""
    transport = httpx.ASGITransport(app=kansallisarkisto_mcp.http_app())

    class Sync:
        def get(self, path: str) -> httpx.Response:
            async def go() -> httpx.Response:
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                    return await c.get(path)

            return asyncio.run(go())

    return Sync()


def test_root_serves_the_landing_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>kansallisarkisto-mcp</title>" in r.text


def test_landing_page_lists_every_registered_tool(client):
    """The page is hand-written; this keeps it from drifting when tools are added."""

    async def names() -> set[str]:
        async with Client(kansallisarkisto_mcp) as c:
            return {t.name for t in await c.list_tools()}

    page = client.get("/").text
    missing = [n for n in asyncio.run(names()) if f"<code>{n}</code>" not in page]
    assert missing == []


def test_health_route(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_reports_not_ready_without_a_table(client, monkeypatch, tmp_path):
    """/health answers the process; /ready answers whether a search would work.

    Conflating them routes traffic to a server whose every tool call is an error
    message — the image ships without data on purpose, so the two states are
    genuinely different.
    """
    from ra_mcp_kansallisarkisto_mcp import tools

    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    monkeypatch.setattr(tools, "_search", None)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not ready"
    # Liveness is unaffected: restarting the process would not conjure a table.
    assert client.get("/health").status_code == 200


def test_ready_reports_ready_once_the_table_is_searchable(client, monkeypatch, df_search):
    from ra_mcp_kansallisarkisto_mcp import tools

    monkeypatch.setattr(tools, "_search", df_search)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "table": "df"}


def test_health_is_liveness_and_stays_ok_without_a_table(client, monkeypatch, tmp_path):
    """Liveness must not depend on the data. The server boots without a table on
    purpose, so a probe that failed there would restart a healthy process."""
    from ra_mcp_kansallisarkisto_mcp import tools

    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    monkeypatch.setattr(tools, "_search", None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_is_503_when_the_table_is_missing(client, monkeypatch, tmp_path):
    """The gap this route closes: /health alone reported 'ok' on a server whose
    every tool call answered with the missing-table error."""
    from ra_mcp_kansallisarkisto_mcp import tools

    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    monkeypatch.setattr(tools, "_search", None)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not ready"
    assert "df table is not available" in r.json()["reason"]


def test_ready_is_200_once_the_table_is_there(client, monkeypatch, tmp_path):
    import lancedb

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_df
    from ra_mcp_kansallisarkisto_mcp import tools

    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), DF_FIXTURE)
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", uri)
    monkeypatch.setattr(tools, "_search", None)
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "table": "df"}
