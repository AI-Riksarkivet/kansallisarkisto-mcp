"""End-to-end MCP smoke test: real client, real server, real LanceDB tables.

Run by `dagger call test-mcp` against the production image with the test fixtures
(18 df charters, 12 voudintilit pages) ingested into tables mounted at /data, and
usable as-is against a deployment holding the full corpora: every record it names
exists in both. Exercises the full stack — image entrypoint, streamable-HTTP
transport, tool dispatch, LanceDB full-text search, formatter.
"""

from __future__ import annotations

import asyncio
import os

from fastmcp import Client

MCP_URL = os.environ.get("MCP_URL", "http://kansallisarkisto-mcp:8000/mcp")
# In the fixture: a 1443-1445 charter issued at Raseborg, and a 1347 Swedish one
# from Åbo whose transcript mentions the king.
RANGED_DF = 1031
# Ylä-Satakunnan tilikirja 1585 (reference 2372), page 16 of 40 — Gödik Fincke's grant.
PAGE = "1578628789_0016"
TOOLS = {"df_search", "df_get_charter", "voudintilit_search", "voudintilit_get_page"}


def _text(result: object) -> str:
    content = getattr(result, "content", []) or []
    return "\n".join(getattr(block, "text", "") for block in content)


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        raise SystemExit(1)


async def main() -> None:
    async with Client(MCP_URL) as client:
        tools = {tool.name for tool in await client.list_tools()}
        _check("tools/list exposes the df and voudintilit tools", TOOLS <= tools, f"got {sorted(tools)}")

        hits = _text(await client.call_tool("df_search", {"keyword": "konung", "limit": 5}))
        _check("df_search returns formatted hits", "Diplomatarium Fennicum search results" in hits, hits[:300])
        _check("df_search leads each hit with its DF number", "**DF " in hits, hits[:300])

        # Accent folding and Swedish stemming are index-time settings; a wrong
        # index config is invisible in unit tests that only search exact forms.
        folded = _text(await client.call_tool("df_search", {"keyword": "Abo", "limit": 5}))
        _check("df_search folds accents (Abo finds Åbo)", "**DF " in folded, folded[:300])

        ranged = _text(await client.call_tool("df_search", {"keyword": "Raseborg", "year_min": 1444, "year_max": 1444}))
        _check("df_search dates by interval overlap", f"**DF {RANGED_DF}**" in ranged, ranged[:300])

        charter = _text(await client.call_tool("df_get_charter", {"df_number": RANGED_DF}))
        _check("df_get_charter renders the full charter", f"**DF {RANGED_DF}**" in charter and "Transcript:" in charter, charter[:300])

        pages = _text(await client.call_tool("voudintilit_search", {"keyword": "Bödich Fincke", "limit": 25}))
        _check("voudintilit_search returns cited pages", "Voudintilit search results" in pages and f"page {PAGE}" in pages, pages[:300])

        page = _text(await client.call_tool("voudintilit_get_page", {"page_id": PAGE}))
        _check("voudintilit_get_page cites the page and links its image", "**2372 Ylä-Satakunnan tilikirja 1585, p. 16**" in page and "aineistoId=1578628789" in page, page[:300])
        _check("voudintilit_get_page names the neighbouring pages", "Previous page: 1578628789_0015" in page and "Next page: 1578628789_0017" in page, page[:400])

    print("OK: MCP smoke test passed (9 checks)")


if __name__ == "__main__":
    # An uncaught exception (connection refused, protocol error) exits non-zero
    # with its traceback — exactly what the harness needs.
    asyncio.run(main())
