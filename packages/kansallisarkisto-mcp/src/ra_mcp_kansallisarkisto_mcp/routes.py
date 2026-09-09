"""Plain HTTP routes beside /mcp: the landing page, and the two probes.

The landing page is what a browser sees at the server root; it lives inside the
package so it ships in the wheel and the Docker image, where docs/ does not.

``/health`` and ``/ready`` answer different questions, and conflating them is
what made the earlier single probe misleading. The server boots on purpose
without a table — that is a deliberate design choice, so that a missing mount is
a readable message rather than a crash loop — which means "the process is up"
and "the process can answer a search" are genuinely different states. A single
always-200 probe reported the first while an orchestrator needed the second, and
would happily route traffic to a server whose every tool call returned the
missing-table error.

So: ``/health`` is liveness (is the process serving HTTP at all — restart it if
not), ``/ready`` is readiness (can it actually search — hold traffic back until
it can). Same split as ra-mcp.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

_INDEX_HTML = files("ra_mcp_kansallisarkisto_mcp").joinpath("assets/index.html").read_text(encoding="utf-8")


def register_routes(mcp: FastMCP, readiness: Callable[[], tuple[bool, str]]) -> None:
    """Register the landing page and the liveness/readiness probes.

    ``readiness`` is injected rather than imported so this module stays free of a
    dependency on ``tools`` — which imports *this* module, and would otherwise
    make a cycle. Same reason ``register_df_tools`` takes ``get_search``.
    """

    @mcp.custom_route("/", methods=["GET"])
    async def root(_: Request) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        # Liveness only. Deliberately does not touch LanceDB: a probe that fails
        # when the data is missing would restart a process that is working
        # exactly as designed.
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/ready", methods=["GET"])
    async def ready(_: Request) -> JSONResponse:
        ok, detail = readiness()
        if ok:
            return JSONResponse({"status": "ready", "table": detail})
        return JSONResponse({"status": "not ready", "reason": detail}, status_code=503)
