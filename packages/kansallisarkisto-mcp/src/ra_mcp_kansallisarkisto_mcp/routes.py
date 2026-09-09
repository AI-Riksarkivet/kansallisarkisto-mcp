"""Plain HTTP routes beside /mcp: the landing page, liveness and readiness.

The landing page is what a browser sees at the server root; it lives inside the
package so it ships in the wheel and the Docker image, where docs/ does not.

`/health` and `/ready` answer different questions, and conflating them is what
sends traffic to a server that cannot serve. The process boots deliberately
without data — the image ships empty and the table is mounted separately — so
"the process is up" and "a search will work" are genuinely different states.
"""

from __future__ import annotations

import logging
from importlib.resources import files

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from ra_mcp_kansallisarkisto_lib.config import DF_TABLE

logger = logging.getLogger(__name__)

_INDEX_HTML = files("ra_mcp_kansallisarkisto_mcp").joinpath("assets/index.html").read_text(encoding="utf-8")


def register_routes(mcp: FastMCP) -> None:
    @mcp.custom_route("/", methods=["GET"])
    async def root(_: Request) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        """Liveness: the process is running. Restarting it would not help with
        anything else, so this stays 200 even with no table mounted."""
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_: Request) -> JSONResponse:
        """Readiness: a search would actually succeed.

        Runs the same one-row probe the boot check uses, because listing table
        names only reads the manifest — which stays readable in the case that
        bites hardest, a table whose data files the runtime user cannot read.
        503 so an orchestrator holds traffic back rather than routing it to a
        server whose every tool call is an error message.
        """
        # Imported here rather than at module scope: routes are registered while
        # tools is still being imported, so a top-level import would cycle.
        from ra_mcp_kansallisarkisto_mcp.errors import MissingTableError
        from ra_mcp_kansallisarkisto_mcp.tools import get_search

        try:
            get_search().search("probe", limit=1)
        except MissingTableError as exc:
            return JSONResponse({"status": "not ready", "table": DF_TABLE, "reason": str(exc)}, status_code=503)
        except Exception as exc:
            # The detail belongs in the log, not the probe body: a readiness
            # endpoint is usually reachable from further away than the logs are.
            logger.exception("readiness probe failed")
            return JSONResponse(
                {"status": "not ready", "table": DF_TABLE, "reason": f"the table is present but cannot be queried ({type(exc).__name__})"},
                status_code=503,
            )
        return JSONResponse({"status": "ready", "table": DF_TABLE})
