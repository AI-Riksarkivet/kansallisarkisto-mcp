"""The non-MCP HTTP routes: the landing page at / and the health probes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from ra_mcp_kansallisarkisto_mcp.tools import kansallisarkisto_mcp

FIXTURES = Path(__file__).parents[2] / "kansallisarkisto-lib" / "tests" / "fixtures"
DF_FIXTURE = FIXTURES / "df_sample.jsonl"
VOUDINTILIT_FIXTURE = FIXTURES / "voudintilit_sample.jsonl"
VOUDINTILIT_ASTIA_FIXTURE = FIXTURES / "voudintilit_astia_sample.jsonl"
TUOMIOKIRJAT_FIXTURE = FIXTURES / "tuomiokirjat_sample.jsonl"
TUOMIOKIRJAT_ASTIA_FIXTURE = FIXTURES / "tuomiokirjat_astia_sample.jsonl"

READY = {"status": "ready", "table": "df, voudintilit, tuomiokirjat"}


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


@pytest.fixture
def tools(monkeypatch):
    """The tools module with both facades unbuilt, so a readiness test measures the
    URI it sets rather than a facade some earlier test left behind."""
    from ra_mcp_kansallisarkisto_mcp import tools

    monkeypatch.setattr(tools, "_search", None)
    monkeypatch.setattr(tools, "_voudintilit_search", None)
    monkeypatch.setattr(tools, "_tuomiokirjat_search", None)
    return tools


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


def test_ready_reports_not_ready_without_a_table(client, monkeypatch, tmp_path, tools):
    """/health answers the process; /ready answers whether a search would work.

    Conflating them routes traffic to a server whose every tool call is an error
    message — the image ships without data on purpose, so the two states are
    genuinely different.
    """
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not ready"
    # Liveness is unaffected: restarting the process would not conjure a table.
    assert client.get("/health").status_code == 200


def test_ready_reports_ready_once_every_table_is_searchable(client, monkeypatch, tools, df_search, voudintilit_search, tuomiokirjat_search):
    monkeypatch.setattr(tools, "_search", df_search)
    monkeypatch.setattr(tools, "_voudintilit_search", voudintilit_search)
    monkeypatch.setattr(tools, "_tuomiokirjat_search", tuomiokirjat_search)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == READY


def test_health_is_liveness_and_stays_ok_without_a_table(client, monkeypatch, tmp_path, tools):
    """Liveness must not depend on the data. The server boots without a table on
    purpose, so a probe that failed there would restart a healthy process."""
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_is_503_when_the_table_is_missing(client, monkeypatch, tmp_path, tools):
    """The gap this route closes: /health alone reported 'ok' on a server whose
    every tool call answered with the missing-table error."""
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", str(tmp_path / "empty"))
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not ready"
    assert "df table is not available" in r.json()["reason"]


def test_ready_is_503_while_one_corpus_is_missing(client, monkeypatch, tmp_path, tools):
    """A server that can search df but not voudintilit answers half its tools with the
    missing-table error — the state /ready exists to keep traffic away from."""
    import lancedb

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_df

    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), DF_FIXTURE)
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", uri)
    r = client.get("/ready")
    assert r.status_code == 503
    assert "voudintilit table is not available" in r.json()["reason"]


def test_ready_is_503_while_df_is_missing(client, monkeypatch, tmp_path, tools):
    import lancedb

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_voudintilit

    uri = str(tmp_path / "db")
    ingest_voudintilit(lancedb.connect(uri), VOUDINTILIT_FIXTURE, VOUDINTILIT_ASTIA_FIXTURE)
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", uri)
    r = client.get("/ready")
    assert r.status_code == 503
    assert "df table is not available" in r.json()["reason"]


def test_ready_is_200_once_the_tables_are_there(client, monkeypatch, tmp_path, tools):
    import lancedb

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_df, ingest_tuomiokirjat, ingest_voudintilit

    uri = str(tmp_path / "db")
    db = lancedb.connect(uri)
    ingest_df(db, DF_FIXTURE)
    ingest_voudintilit(db, VOUDINTILIT_FIXTURE, VOUDINTILIT_ASTIA_FIXTURE)
    ingest_tuomiokirjat(db, TUOMIOKIRJAT_FIXTURE, TUOMIOKIRJAT_ASTIA_FIXTURE)
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", uri)
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == READY


def test_ready_is_503_while_tuomiokirjat_is_missing(client, monkeypatch, tmp_path, tools):
    import lancedb

    from ra_mcp_kansallisarkisto_lib.ingest import ingest_df, ingest_voudintilit

    uri = str(tmp_path / "db")
    db = lancedb.connect(uri)
    ingest_df(db, DF_FIXTURE)
    ingest_voudintilit(db, VOUDINTILIT_FIXTURE, VOUDINTILIT_ASTIA_FIXTURE)
    monkeypatch.setattr(tools.settings, "ka_lancedb_uri", uri)
    r = client.get("/ready")
    assert r.status_code == 503
    assert "tuomiokirjat table is not available" in r.json()["reason"]
