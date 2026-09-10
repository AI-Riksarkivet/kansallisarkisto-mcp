"""The `voudintilit_search` and `voudintilit_get_page` tools over the bailiff accounts.

Registered against a server, like the df tools, so the VoudintilitSearch facade is
resolved per call (and swapped in tests). Both handlers are sync for the same reason
the df ones are: LanceDB's API is blocking, and FastMCP dispatches a sync tool to a
worker thread instead of running it on the event loop.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ra_mcp_kansallisarkisto_lib.config import DEFAULT_LIMIT, MAX_LIMIT
from ra_mcp_kansallisarkisto_lib.dataset import require_keyword, require_ordered_range
from ra_mcp_kansallisarkisto_lib.telemetry import mark_span_error
from ra_mcp_kansallisarkisto_mcp.errors import answer
from ra_mcp_kansallisarkisto_mcp.formatter import format_page, format_voudintilit_results


def register_voudintilit_tools(mcp: FastMCP, get_search) -> None:
    @mcp.tool(
        name="voudintilit_search",
        tags={"kansallisarkisto", "voudintilit", "bailiff-accounts", "search"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Search voudintilit — 98,945 machine-transcribed pages of the Swedish crown's bailiff "
            "accounts for the Häme and Satakunta bailiwicks in Finland, 1539–1635, held by "
            "Kansallisarkisto. Each hit is ONE PAGE of an account book — a volume holding one "
            "bailiwick's accounts for one year — not a whole document. "
            "SEARCH IN EARLY-MODERN SWEDISH, NOT FINNISH: the accounts were kept in the "
            "administrative language of the Swedish realm, so search Swedish words in period "
            "spelling ('smör', 'konung'); people, farms and villages appear as the scribe wrote "
            "them. Only the catalogue labels — collection and account-book titles — are Finnish. "
            "Every hit leads with its citation — reference number, account book, year and page, "
            "e.g. '2372 Ylä-Satakunnan tilikirja 1585, p. 16' — followed by its page id and a link "
            "to the page image in Astia, Kansallisarkisto's digital archive. Give the user the "
            "citation and the link, and pass the page id to voudintilit_get_page for the full text "
            "and the neighbouring pages. The text is machine-recognised handwriting, so check any "
            "quotation against the image. "
            'QUERY SYNTAX: several words means all of them must appear; "quote a phrase" to '
            "require the exact sequence. AND, OR and NOT are not operators and are matched as "
            "ordinary words; to widen, drop a word or pass match_all=false. Spelling was never "
            "standardised, so retry a thin search with fuzzy=1 on a base form. "
            "Example: voudintilit_search(keyword='smör', collection='hame', year_min=1540, year_max=1560)."
        ),
    )
    def voudintilit_search(
        keyword: Annotated[
            str,
            Field(
                description=(
                    "Search term, in early-modern Swedish and period spelling. Swedish stemming and "
                    'accent folding are applied. Several words require all of them; "quoted words" '
                    "require that exact phrase. The account-book title and collection are indexed "
                    "with the page text, so a title word such as 'Maakirja' (land register) works here too."
                )
            ),
        ],
        offset: Annotated[int, Field(description="Pagination start (0, 25, 50, ...).", ge=0)] = 0,
        limit: Annotated[int, Field(description=f"Max results (1–{MAX_LIMIT}).", ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        collection: Annotated[
            Literal["hame", "satakunta"] | None,
            Field(description=("Which bailiwicks: 'hame' — Hämeen voutikuntien tilejä, the Häme accounts (54,560 pages) — or 'satakunta' — Satakunnan voutikuntien tilejä (44,385).")),
        ] = None,
        account_book: Annotated[
            str | None,
            Field(
                description=(
                    "Account-book title, as a case-insensitive substring over 292 Finnish titles — it "
                    "matches every title containing it. 'Sääksmäen' covers 28 titles (14,125 pages), the "
                    "largest Sääksmäen voutikunnan tilikirja (6,254); 'Ylä-Satakunnan' 33 titles (16,296); "
                    "'Hauhon' 16 (8,263); 'Hämeen linnan' 5 (5,723); 'Maakirja' the 80 land-register titles (32,330)."
                )
            ),
        ] = None,
        year_min: Annotated[
            int | None,
            Field(
                description=(
                    "Earliest year of the account. Pages whose year range overlaps [year_min, year_max] "
                    "are returned. The Satakunta archive catalogue volume has no year and is left out "
                    "whenever a year is set; one Ylä-Satakunnan volume (reference 2523) is catalogued "
                    "as 1615–1516 and is treated as 1615."
                )
            ),
        ] = None,
        year_max: Annotated[int | None, Field(description="Latest year of the account.")] = None,
        match_all: Annotated[
            bool,
            Field(description="Require every word of the keyword (default). Set false to match any word; the total then counts pages matching only one word."),
        ] = True,
        fuzzy: Annotated[
            int,
            Field(
                description=(
                    "Edit distance per term, 0-2. Default 0. Spelling was never standardised, so "
                    "fuzzy=1 is the right second attempt when a search looks thin. A fuzzy term skips "
                    'stemming, so pass a base form. Cannot be combined with a "quoted phrase".'
                ),
                ge=0,
                le=2,
            ),
        ] = 0,
    ) -> str:
        if err := require_keyword(keyword, "'smör' or 'konung'"):
            mark_span_error(err, "validation")
            return err
        if err := require_ordered_range(year_min, year_max, "year"):
            mark_span_error(err, "validation")
            return err
        return answer(
            "voudintilit_search",
            lambda: format_voudintilit_results(
                get_search().search(
                    keyword,
                    limit=limit,
                    offset=offset,
                    collection=collection,
                    account_book=account_book,
                    year_min=year_min,
                    year_max=year_max,
                    match_all=match_all,
                    fuzzy=fuzzy,
                )
            ),
        )

    @mcp.tool(
        name="voudintilit_get_page",
        tags={"kansallisarkisto", "voudintilit", "bailiff-accounts"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Fetch one voudintilit page by its page id — '<volume>_<page>', e.g. '1578628789_0016', "
            "shown on every voudintilit_search hit — and return its full text with its citation "
            "(reference number, account book, year, page), collection, the link to the page image "
            "in Astia, and the ids of the previous and next pages in the same volume. Accounts run "
            "across pages, so follow those ids to read on. The text is machine-recognised, so verify "
            "quotations against the image. Example: voudintilit_get_page(page_id='1578628789_0016')."
        ),
    )
    def voudintilit_get_page(
        page_id: Annotated[str, Field(description="The page id from a voudintilit_search hit, '<volume>_<page>', e.g. '1578628789_0016'.")],
    ) -> str:
        return answer("voudintilit_get_page", lambda: format_page(get_search().get_page(page_id), page_id))
