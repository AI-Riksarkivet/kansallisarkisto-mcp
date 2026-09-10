"""Transport selection and the boot-time table-status line in the server entrypoint."""

from __future__ import annotations

import logging

import lancedb
import pytest

from ra_mcp_kansallisarkisto_lib.ingest import ingest_df
from ra_mcp_kansallisarkisto_mcp import server
from ra_mcp_kansallisarkisto_mcp.settings import Settings


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


def test_present_table_is_reported_at_boot_with_its_size(caplog, monkeypatch, tmp_path, df_fixture):
    """'tables: df' says a table is there; the row count says whether it is the
    corpus or a fixture — the difference between a deploy and a mistake."""
    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), df_fixture)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.INFO):
        server.log_table_status()
    assert "tables: df (19 rows)" in caplog.text


def test_boot_names_the_version(caplog, monkeypatch):
    """The Space log is the only place to learn which release is serving."""
    monkeypatch.setattr(server, "kansallisarkisto_mcp", RunRecorder())
    monkeypatch.setattr(server, "log_table_status", lambda: None)
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "stdio")
    with caplog.at_level(logging.INFO):
        server.main()
    assert "kansallisarkisto-mcp 0." in caplog.text


def test_fastmcp_logs_through_the_root_handler(monkeypatch):
    """FastMCP installs a rich handler on its own logger that wraps a one-line
    warning over seven at console width, and keeps it from the root handler. After
    main() its records go where ours go, in the same format."""
    monkeypatch.setattr(server, "kansallisarkisto_mcp", RunRecorder())
    monkeypatch.setattr(server, "log_table_status", lambda: None)
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "stdio")
    server.main()
    fastmcp_logger = logging.getLogger("fastmcp")
    assert fastmcp_logger.handlers == []
    assert fastmcp_logger.propagate is True


def test_missing_table_is_reported_at_boot(caplog, monkeypatch, tmp_path):
    """Otherwise a wrong URI surfaces only on the first tool call."""
    uri = str(tmp_path / "empty")
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert "has no 'df' table" in caplog.text
    assert uri in caplog.text


def _ingest_all(uri: str, fixtures) -> None:
    """Every corpus's sample into one database; `fixtures` is the `all_fixtures` fixture."""
    from ra_mcp_kansallisarkisto_lib.ingest import ingest_tuomiokirjat, ingest_voudintilit

    db = lancedb.connect(uri)
    ingest_df(db, fixtures["df"])
    ingest_voudintilit(db, *fixtures["voudintilit"])
    ingest_tuomiokirjat(db, *fixtures["tuomiokirjat"])


@pytest.fixture
def all_fixtures(df_fixture, voudintilit_fixture, voudintilit_astia_fixture, tuomiokirjat_fixture, tuomiokirjat_astia_fixture):
    return {"df": df_fixture, "voudintilit": (voudintilit_fixture, voudintilit_astia_fixture), "tuomiokirjat": (tuomiokirjat_fixture, tuomiokirjat_astia_fixture)}


def test_boot_probe_runs_a_real_query_on_a_healthy_table(caplog, monkeypatch, tmp_path, all_fixtures):
    """Listing table names only reads the manifest — the probe must touch the index."""
    uri = str(tmp_path / "db")
    _ingest_all(uri, all_fixtures)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert caplog.text == ""


def test_missing_voudintilit_table_is_reported_at_boot(caplog, monkeypatch, tmp_path, df_fixture):
    """Each corpus is checked on its own: df being there says nothing about voudintilit."""
    uri = str(tmp_path / "db")
    ingest_df(lancedb.connect(uri), df_fixture)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert "has no 'voudintilit' table" in caplog.text
    assert "has no 'tuomiokirjat' table" in caplog.text
    assert "has no 'df' table" not in caplog.text


def test_boot_probe_checks_every_present_table(caplog, monkeypatch, tmp_path, all_fixtures):
    uri = str(tmp_path / "db")
    _ingest_all(uri, all_fixtures)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", uri)

    class Unreadable:
        def __init__(self, _db): ...

        def search(self, *_args, **_kwargs):
            raise RuntimeError("lance error: Not found: /data/voudintilit.lance/_indices/x/tokens.lance")

    monkeypatch.setattr(server, "VoudintilitSearch", Unreadable)
    with caplog.at_level(logging.ERROR):
        server.log_table_status()
    assert "The 'voudintilit' table" in caplog.text
    assert "cannot be queried" in caplog.text
    assert "The 'df' table" not in caplog.text


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


def test_staging_is_off_by_default():
    assert Settings.model_fields["ka_mcp_stage_datasets"].default is False


def test_main_stages_before_the_boot_check(recorder, monkeypatch):
    """The boot check has to look at the copy the server will actually serve."""
    order: list[str] = []
    monkeypatch.setattr(server, "stage_tables", lambda: order.append("stage"))
    monkeypatch.setattr(server, "log_table_status", lambda: order.append("status"))
    monkeypatch.setattr(server.settings, "ka_mcp_transport", "stdio")
    server.main()
    assert order == ["stage", "status"]


def test_boot_staging_serves_the_local_copy(caplog, monkeypatch, tmp_path, df_fixture):
    """On a Space the mount is a FUSE layer lance cannot query under load, so the
    server must read the copy, not the mount."""
    mount, local = str(tmp_path / "mount"), tmp_path / "local"
    ingest_df(lancedb.connect(mount), df_fixture)
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", mount)
    monkeypatch.setattr(server.settings, "ka_mcp_stage_datasets", True)
    monkeypatch.setattr(server.settings, "ka_mcp_stage_dir", str(local))
    server.stage_tables()
    assert server.settings.lancedb_uri == str(local)
    with caplog.at_level(logging.INFO):
        server.log_table_status()
    assert f"LanceDB at {local} — tables: df" in caplog.text


def test_boot_staging_off_leaves_the_configured_uri(monkeypatch, tmp_path):
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", str(tmp_path / "mount"))
    monkeypatch.setattr(server.settings, "ka_mcp_stage_datasets", False)
    server.stage_tables()
    assert server.settings.lancedb_uri == str(tmp_path / "mount")


def test_failed_staging_falls_back_to_the_configured_uri(monkeypatch, tmp_path):
    """Nothing to copy is not fatal: the server serves the configured URI, and the
    boot check reports the missing table exactly as it would without staging."""
    monkeypatch.setattr(server.settings, "ka_lancedb_uri", str(tmp_path / "absent"))
    monkeypatch.setattr(server.settings, "ka_mcp_stage_datasets", True)
    monkeypatch.setattr(server.settings, "ka_mcp_stage_dir", str(tmp_path / "local"))
    server.stage_tables()
    assert server.settings.lancedb_uri == str(tmp_path / "absent")
