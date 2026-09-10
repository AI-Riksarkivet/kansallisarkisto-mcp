"""Entrypoint: serve the Kansallisarkisto MCP over stdio or streamable HTTP."""

from __future__ import annotations

import atexit
import logging
import sys
from pathlib import Path

from ra_mcp_kansallisarkisto_lib.config import DF_TABLE, stage_lancedb
from ra_mcp_kansallisarkisto_lib.dataset import get_lancedb, table_names
from ra_mcp_kansallisarkisto_lib.search_operations import DfSearch
from ra_mcp_kansallisarkisto_mcp.settings import settings
from ra_mcp_kansallisarkisto_mcp.telemetry import init_telemetry, shutdown_telemetry
from ra_mcp_kansallisarkisto_mcp.tools import kansallisarkisto_mcp

logger = logging.getLogger(__name__)

# The boot probe runs one real query. The term need not match anything — what is
# being tested is whether the query can run at all, which means touching the
# full-text index files that a listing of table names never opens.
PROBE_KEYWORD = "probe"


def stage_tables() -> None:
    """Copy the tables onto local disk before anything reads them, when asked to.

    Opt-in via KA_MCP_STAGE_DATASETS, for a Hugging Face Space — see
    ra_mcp_kansallisarkisto_lib.config.stage_lancedb for why. On success every later
    read of settings.lancedb_uri, the boot check's and the tools' alike, resolves to
    the copy. On failure the configured URI stands, so the server still boots and
    reports what it found there.
    """
    if not settings.ka_mcp_stage_datasets:
        return
    staged = stage_lancedb(settings.lancedb_uri, Path(settings.ka_mcp_stage_dir))
    if staged is not None:
        settings.ka_lancedb_uri = staged


def log_table_status() -> None:
    """Say at boot which tables the configured URI actually holds.

    The server deliberately boots without data so a missing table is a tool
    message rather than a crash — which otherwise surfaces only on the first
    call. Listing what is there separates 'nothing is mounted' from 'the URI
    points somewhere else'.
    """
    uri = settings.lancedb_uri
    try:
        tables = table_names(get_lancedb(uri))
    except Exception:
        # A traceback is worth having here: an unopenable database at boot is a
        # deployment fault (wrong URI, unreadable mount), not a user error.
        logger.exception("Cannot open the LanceDB database at %s", uri)
        return
    if DF_TABLE not in tables:
        logger.error(
            "LanceDB at %s has no '%s' table — every charter tool call will return the missing-table error. Tables present: %s",
            uri,
            DF_TABLE,
            ", ".join(tables) or "(none)",
        )
        return

    logger.info("LanceDB at %s — tables: %s", uri, ", ".join(tables))
    probe_table_readable(uri)


def probe_table_readable(uri: str) -> None:
    """Run one real query at boot, so an unreadable table is diagnosed here.

    Listing table names only reads the manifest, which stays readable in exactly
    the case that bites hardest: lance writes its data and index files mode 0600,
    so a table copied into an image (docker ``COPY``, Dagger ``WithDirectory``)
    without preserving ownership belongs to root and the non-root runtime user
    cannot read it. Worse, lance reports that ``EACCES`` as ``Not found``, which
    sends you looking for a missing file that is sitting right there.

    Cheap enough to always run, and never fatal: the server still boots, because
    a table that appears later (a late mount) should start working.
    """
    try:
        DfSearch(get_lancedb(uri)).search(PROBE_KEYWORD, limit=1)
    except Exception:
        logger.exception(
            "The '%s' table at %s is present but cannot be queried, so every search will fail. "
            "The usual cause is file ownership rather than a missing file: lance writes mode-0600 "
            "files and reports a permission error as 'Not found'. Copy the table in with "
            "--chown=1000:1000, or mount a directory owned by uid 1000.",
            DF_TABLE,
            uri,
        )


def main() -> None:
    # stderr keeps stdio transport clean (stdout is the protocol channel) and is
    # what container log viewers surface.
    logging.basicConfig(
        level=settings.log_level.upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Before anything that might be worth tracing, and after logging is
    # configured so the log bridge picks up the same root logger. A no-op unless
    # KA_MCP_OTEL_ENABLED is set. The atexit flush matters most for stdio, where
    # the process exits at the end of every session and would otherwise drop its
    # last batch of spans.
    init_telemetry()
    atexit.register(shutdown_telemetry)
    # Before the boot check, so the check inspects the copy the server will serve.
    stage_tables()
    log_table_status()
    if settings.ka_mcp_transport == "http":
        # Behind a TLS-terminating proxy, uvicorn must trust X-Forwarded-Proto or it builds
        # redirects with scheme http — so a client asking for '/mcp/' is sent to http://…/mcp
        # and most HTTP libraries refuse that https->http downgrade. Trusting any peer is safe
        # here because the container is only reachable through that proxy.
        kansallisarkisto_mcp.run(
            transport="http",
            host=settings.host,
            port=settings.port,
            uvicorn_config={"proxy_headers": True, "forwarded_allow_ips": "*"},
        )
    elif settings.ka_mcp_transport == "stdio":
        kansallisarkisto_mcp.run()
    else:
        # A typo must not silently serve stdio inside a container expecting HTTP.
        raise ValueError(f"unknown KA_MCP_TRANSPORT '{settings.ka_mcp_transport}' — use 'stdio' or 'http'")


if __name__ == "__main__":
    main()
