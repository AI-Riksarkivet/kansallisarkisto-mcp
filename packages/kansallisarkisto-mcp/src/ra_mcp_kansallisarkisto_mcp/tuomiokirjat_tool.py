"""The `tuomiokirjat_search` and `tuomiokirjat_get_page` tools over the court records.

Registered against a server, like the other corpora's tools, so the TuomiokirjatSearch
facade is resolved per call (and swapped in tests). Both handlers are sync: LanceDB's
API is blocking, and FastMCP dispatches a sync tool to a worker thread instead of
running it on the event loop.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ra_mcp_kansallisarkisto_lib.config import DEFAULT_LIMIT, MAX_LIMIT
from ra_mcp_kansallisarkisto_lib.dataset import require_keyword, require_ordered_range
from ra_mcp_kansallisarkisto_lib.telemetry import mark_span_error
from ra_mcp_kansallisarkisto_mcp.errors import Answer, answer, found, paging, summary
from ra_mcp_kansallisarkisto_mcp.formatter import format_court_page, format_tuomiokirjat_results


def register_tuomiokirjat_tools(mcp: FastMCP, get_search) -> None:
    @mcp.tool(
        name="tuomiokirjat_search",
        tags={"kansallisarkisto", "tuomiokirjat", "court-records", "search"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Search tuomiokirjat — 7.8 million machine-transcribed pages of Finnish lower-court "
            "records, 1610–1931, held by Kansallisarkisto: the judgement books and minutes of the "
            "town courts (raastuvanoikeus), district courts (kihlakunnanoikeus, by tuomiokunta), "
            "town bailiffs' courts (kämnerinoikeus), land-partition courts and two appeal courts, "
            "from 223 archives. Each hit is ONE PAGE of a court volume, not a case; cases run across "
            "pages. SEARCH IN SWEDISH, NOT FINNISH: the courts wrote Swedish until the late 19th "
            "century, and in period spelling — personal names and farms as the clerk spelled them. "
            "Only the catalogue labels — archive and series names — are Finnish. Every hit leads "
            "with its citation: series, the volume's signum, year and page, e.g. 'Porin "
            "raastuvanoikeuden tuomiokirjat a:1 1622–1639, p. 66', with the archive on the next "
            "line, then the page id and a link to the page image in Astia, Kansallisarkisto's "
            "digital archive. Give the user the citation and the link, and pass the page id to "
            "tuomiokirjat_get_page for the full text and the neighbouring pages. The text is "
            "machine-recognised handwriting over three centuries, so check any quotation against "
            "the image. The corpus is uneven: the 1910s alone are 1.1 million pages and the whole "
            "17th century 240,000, so a thin result for an early decade is the archive, not the "
            'query. QUERY SYNTAX: several words means all of them must appear; "quote a phrase" '
            "to require the exact sequence. AND, OR and NOT are not operators and are matched as "
            "ordinary words; to widen, drop a word or pass match_all=false. Spelling was never "
            "standardised, so retry a thin search with fuzzy=1 on a base form. Common words match "
            "more than 10,000 pages — the total then reads 10000+ — so narrow by collection, "
            "series and years. Example: tuomiokirjat_search(keyword='hustru', series='Turun "
            "raastuvanoikeuden', year_min=1650, year_max=1660)."
        ),
    )
    def tuomiokirjat_search(
        keyword: Annotated[
            str,
            Field(
                description=(
                    "Search term, in Swedish and period spelling. Swedish stemming and accent folding "
                    'are applied. Several words require all of them; "quoted words" require that '
                    "exact phrase; 'bref|breff' matches either spelling. A trailing * (prefix search) "
                    "is not available on this corpus — it is too large to hold a vocabulary — so list "
                    "the spellings, or use fuzzy=1. Only the page text is indexed — use the collection "
                    "and series filters to reach a court by name."
                )
            ),
        ],
        offset: Annotated[int, Field(description="Pagination start (0, 25, 50, ...).", ge=0)] = 0,
        limit: Annotated[int, Field(description=f"Max results (1–{MAX_LIMIT}).", ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        collection: Annotated[
            str | None,
            Field(
                description=(
                    "Archive, as a case-insensitive substring over 223 Finnish names — it matches every "
                    "archive containing it. Town courts: 'Raastuvanoikeuksien renovoidut tuomiokirjat' "
                    "(the 17th–18th-century town courts together, 611,000 pages), 'Viipurin raastuvanoikeuden' "
                    "(378,000), 'Turun raastuvanoikeuden' (82,000). District courts by tuomiokunta: "
                    "'Etelä-Pohjanmaan' (130,000), 'Ylä-Satakunnan' (125,000 + 102,000), 'Raaseporin' "
                    "(121,000), 'Rautalammin' (118,000). Appeal courts: 'Viipurin hovioikeuden' (299,000), "
                    "'Vaasan hovioikeuden' (189,000). 'tuomiokunnan' alone reaches every district court."
                )
            ),
        ] = None,
        series: Annotated[
            str | None,
            Field(
                description=(
                    "Series within the archive, as a case-insensitive substring over 444 Finnish names. "
                    "For the 17th–18th-century town courts the series names the court — 'Turun "
                    "raastuvanoikeuden tuomiokirjat' (85,000 pages, 1623–1809), 'Helsingin' (26,000), "
                    "'Porin' (19,000) — so 'Turun' picks out Turku. For the 19th–20th-century district "
                    "courts it names the record type: 'Varsinaisten asioiden pöytäkirjat' (court cases, "
                    "2.5 million pages, 1610–1921) and 'Ilmoitusasioiden pöytäkirjat' (registrations — "
                    "land transfers, mortgages, guardianships — 2.5 million, 1701–1919); combine with "
                    "collection for the district."
                )
            ),
        ] = None,
        year_min: Annotated[
            int | None,
            Field(
                description=(
                    "Earliest year of the volume. Pages whose volume's year range overlaps [year_min, "
                    "year_max] are returned. 83 pages have no year and are left out whenever a year is "
                    "set; 703 are catalogued with the end before the start and are dated to one year "
                    "— the start, unless only the end falls within the corpus (1984–1895 reads as 1895)."
                )
            ),
        ] = None,
        year_max: Annotated[int | None, Field(description="Latest year of the volume.")] = None,
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
        research_context: Annotated[
            str | None,
            Field(description="Brief summary of the user's research goal. Used for logging only."),
        ] = None,
    ) -> str:
        if err := require_keyword(keyword, "'hustru' or 'Larsson'"):
            mark_span_error(err, "validation")
            return err
        if err := require_ordered_range(year_min, year_max, "year"):
            mark_span_error(err, "validation")
            return err

        def run() -> Answer:
            result = get_search().search(keyword, limit=limit, offset=offset, collection=collection, series=series, year_min=year_min, year_max=year_max, match_all=match_all, fuzzy=fuzzy)
            return format_tuomiokirjat_results(result), summary(result)

        return answer(
            "tuomiokirjat_search",
            run,
            keyword=keyword,
            collection=collection,
            series=series,
            year_min=year_min,
            year_max=year_max,
            research_context=research_context,
            **paging(offset, limit, match_all, fuzzy),
        )

    @mcp.tool(
        name="tuomiokirjat_get_page",
        tags={"kansallisarkisto", "tuomiokirjat", "court-records"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Fetch one tuomiokirjat page by its page id — shown on every tuomiokirjat_search hit, "
            "e.g. 'Y4Q4IZcBCao99UPKS6L8' — and return its full text with its citation (series, "
            "signum, year, page), archive, the link to the page image in Astia, and the ids of the "
            "previous and next pages in the same volume. Cases run across pages, so follow those "
            "ids to read on. The text is machine-recognised, so verify quotations against the image. "
            "Example: tuomiokirjat_get_page(page_id='Y4Q4IZcBCao99UPKS6L8')."
        ),
    )
    def tuomiokirjat_get_page(
        page_id: Annotated[str, Field(description="The page id from a tuomiokirjat_search hit, e.g. 'Y4Q4IZcBCao99UPKS6L8'.")],
    ) -> str:

        def run() -> Answer:
            page = get_search().get_page(page_id)
            return format_court_page(page, page_id), found(page)

        return answer("tuomiokirjat_get_page", run, page_id=page_id)
