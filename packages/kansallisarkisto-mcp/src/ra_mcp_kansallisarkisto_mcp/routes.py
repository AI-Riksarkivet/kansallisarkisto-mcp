"""Plain HTTP routes beside /mcp: the landing page and a health probe.

The landing page is what a browser sees at the server root; it lives inside the
package so it ships in the wheel and the Docker image, where docs/ does not.
"""

from __future__ import annotations

from importlib.resources import files

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

_INDEX_HTML = files("ra_mcp_kansallisarkisto_mcp").joinpath("assets/index.html").read_text(encoding="utf-8")


def register_routes(mcp: FastMCP) -> None:
    @mcp.custom_route("/", methods=["GET"])
    async def root(_: Request) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})
