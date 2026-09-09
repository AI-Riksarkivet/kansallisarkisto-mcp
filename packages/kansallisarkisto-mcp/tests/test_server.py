"""Transport selection and the boot-time table-status line in the server entrypoint."""

from __future__ import annotations

import logging

import lancedb
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df
from ra_mcp_kansallisarkisto_mcp import server


class RunRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.fixture
def recorder(monkeypatch):
    rec = RunRecorder()
    monkeypatch.setattr(server, "kansallisarkisto_mcp", rec)
    # The status line opens LanceDB; the transport tests are not about that.
    monkeypatch.setattr(server, "log_table_status", lambda: None)
    return rec


def test_http_transport_serves_on_configured_host_and_port(recorder, monkeypatch):
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "http")
    server.main()
    assert recorder.calls[0]["transport"] == "http"
    assert recorder.calls[0]["host"] == server.settings.host
    assert recorder.calls[0]["port"] == server.settings.port


def test_http_transport_trusts_the_proxy_scheme(recorder, monkeypatch):
    """Without this, redirects behind a TLS proxy point at http:// and clients drop them."""
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "http")
    server.main()
    assert recorder.calls[0]["uvicorn_config"] == {"proxy_headers": True, "forwarded_allow_ips": "*"}


def test_stdio_is_the_default_transport(recorder, monkeypatch):
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "stdio")
    server.main()
    assert recorder.calls == [{}]


def test_unknown_transport_fails_loudly_instead_of_hanging_on_stdio(recorder, monkeypatch):
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "htpp")
    with pytest.raises(ValueError, match="htpp"):
        server.main()
    assert recorder.calls == []


def test_present_table_is_reported_at_boot(caplog, monkeypatch, tmp_path, df_fixture):
    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), df_fixture)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.INFO):
        server.log_table_status()
    assert "tables: df" in caplog.text


def test_missing_table_is_reported_at_boot(caplog, monkeypatch, tmp_path):
    """Otherwise a wrong URI surfaces only on the first tool call."""
    uri = str(tmp_path / "empty")
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert "has no 'df' table" in caplog.text
    assert uri in caplog.text


def test_boot_probe_runs_a_real_query_on_a_healthy_table(caplog, monkeypatch, tmp_path, df_fixture):
    """Listing table names only reads the manifest — the probe must touch the index."""
    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), df_fixture)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert caplog.text == ""


def test_boot_probe_explains_an_unreadable_table(caplog, monkeypatch, tmp_path, df_fixture):
    """lance reports a permission error as 'Not found', which sends you hunting
    for a file that is sitting right there. The boot message has to say so."""
    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), df_fixture)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)

    class Unreadable:
        def __init__(self, _db): ...

        def search(self, *_args, **_kwargs):
            raise RuntimeError("lance error: Not found: /data/df.lance/_indices/x/tokens.lance")

    monkeypatch.setattr(server, "DfSearch", Unreadable)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert "cannot be queried" in caplog.text
    assert "--chown=1000:1000" in caplog.text
