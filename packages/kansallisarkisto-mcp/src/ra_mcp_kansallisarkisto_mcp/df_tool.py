"""The `df_search` and `df_get_charter` tools over the Diplomatarium Fennicum corpus.

Registered against a server rather than defined at import so the DfSearch facade
can be resolved per call (and swapped in tests).

Both handlers are deliberately **sync**. LanceDB's Python API is blocking, and
FastMCP runs a coroutine tool body inline on the event loop while dispatching a
sync one to a worker thread — so declaring these ``async`` would stall every other
in-flight request for the length of a search. LanceDB connections are Send + Sync,
so the threadpool is safe.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ra_mcp_kansallisarkisto_lib.config import DEFAULT_LIMIT, MAX_LIMIT
from ra_mcp_kansallisarkisto_lib.dataset import SearchInputError, require_keyword, require_ordered_range
from ra_mcp_kansallisarkisto_mcp.errors import MissingTableError
from ra_mcp_kansallisarkisto_mcp.formatter import format_charter, format_error, format_search_results

logger = logging.getLogger(__name__)


def register_df_tools(mcp: FastMCP, get_search) -> None:
    @mcp.tool(
        name="df_search",
        tags={"kansallisarkisto", "diplomatarium-fennicum", "charters", "search"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Search Diplomatarium Fennicum — the scholarly edition of 6,876 medieval charters, "
            "letters and account entries concerning Finland, 859–1530, held by Kansallisarkisto. "
            "SEARCH IN PERIOD SPELLING, AND NOT IN FINNISH: the text is early-modern Swedish, "
            "Latin and German (Finland was part of the Swedish realm), so use 'bref' not 'brev', "
            "'konung' not 'kung', and historical place names — 'Åbo' not 'Turku', 'Viborg' not "
            "'Viipuri'. Only the catalogue metadata (index terms, language and country labels) is "
            "in Finnish. 36% of the corpus is catalogued but not transcribed; those charters are "
            "still returned and are findable by place, index term and language, and are marked as "
            "untranscribed. Results carry the DF number, which is the citable identifier — always "
            "surface it, and pass it to df_get_charter for the full transcript. "
            "The text is machine-recognised, so check any quotation against the source. "
            'QUERY SYNTAX: several words means all of them must appear; "quote a phrase" to '
            "require the exact sequence. Do NOT write AND, OR or NOT — they are not operators "
            "here and are matched as ordinary words, so 'bref OR littera' also drags in every "
            "charter containing 'or'. To widen instead, drop a word or pass match_all=false. "
            "Example: df_search(keyword='konung', issuingplace='Åbo', year_min=1300, year_max=1400)."
        ),
    )
    def df_search(
        keyword: Annotated[
            str,
            Field(
                description=(
                    "Search term, in the language of the documents (Swedish, Latin, German) and in "
                    "period spelling. Swedish stemming is applied, so 'konung' also matches 'konungen' "
                    "and 'konungs'; accents are folded, so 'Abo' matches 'Åbo'. Several words require "
                    'all of them; "quoted words" require that exact phrase. AND/OR/NOT are not '
                    "operators and will be searched for literally."
                )
            ),
        ],
        offset: Annotated[int, Field(description="Pagination start (0, 25, 50, ...).", ge=0)] = 0,
        limit: Annotated[int, Field(description=f"Max results (1–{MAX_LIMIT}).", ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
        language: Annotated[
            str | None,
            Field(
                description=(
                    "Exact document language, as an UNACCENTED Finnish label: 'ruotsi' (Swedish, "
                    "3,045 charters), 'latina' (1,638), 'saksa' (German, 1,232), 'venaja' (Russian, "
                    "89). Note 'venaja', not 'venäjä' — the accented form matches nothing."
                )
            ),
        ] = None,
        issuingplace: Annotated[
            str | None,
            Field(description="Place of issue in its historical form, matched as a case-insensitive substring: 'Åbo' (815), 'Stockholm' (687), 'Rom' (359). 2,314 charters record no place."),
        ] = None,
        country: Annotated[
            str | None,
            Field(description="Country of issue, as a Finnish label matched as a case-insensitive substring: 'Suomi' (Finland, 2,249), 'Ruotsi' (Sweden, 1,207), 'Italia' (467)."),
        ] = None,
        year_min: Annotated[int | None, Field(description="Earliest year the charter may fall in. Charters whose dating interval overlaps [year_min, year_max] are returned.")] = None,
        year_max: Annotated[int | None, Field(description="Latest year the charter may fall in.")] = None,
        match_all: Annotated[
            bool,
            Field(
                description=(
                    "Require every word of the keyword (default). Set false to match any word, which "
                    "widens the search when a term may be spelled differently — but the total then "
                    "counts charters matching only one word, so read it as a ceiling rather than a "
                    "count of relevant results."
                )
            ),
        ] = True,
        fuzzy: Annotated[
            int,
            Field(
                description=(
                    "Edit distance per term, 0-2. Default 0. Spelling in these charters is not "
                    "standardised, so exact search finds one scribe's spelling and misses the rest: "
                    "'bref' matches 257 charters, 'breff' matches 1,918, and only 71 overlap. "
                    "fuzzy=1 takes 'bref' to 2,212 and is the right second attempt when a search "
                    "looks thin. It is not the default because a fuzzy term skips stemming, so pass "
                    "a base form ('konung', not 'konungen' — which collapses from 279 hits to 6). "
                    'Cannot be combined with a "quoted phrase".'
                ),
                ge=0,
                le=2,
            ),
        ] = 0,
    ) -> str:
        if err := require_keyword(keyword, "'konung' or 'littera'"):
            return err
        if err := require_ordered_range(year_min, year_max, "year"):
            return err
        try:
            result = get_search().search(
                keyword,
                limit=limit,
                offset=offset,
                language=language,
                issuingplace=issuingplace,
                country=country,
                year_min=year_min,
                year_max=year_max,
                match_all=match_all,
                fuzzy=fuzzy,
            )
        except MissingTableError as exc:
            # A deployment state the operator can fix, so it is explained in full
            # rather than folded into the generic internal-error reply.
            return str(exc)
        except SearchInputError as exc:
            # Raised only by this library's own guards — a blank keyword, a bad
            # page, fuzzy on a quoted phrase — so the message is written for the
            # caller and deserves its sentence, not "an internal ValueError".
            # Deliberately NOT `except ValueError`: lancedb raises that too, and
            # its messages quote dataset paths and internal query structure, which
            # a broad catch would hand straight to a public HTTP client.
            return f"Error: {exc}"
        except Exception as exc:
            # logger.exception keeps the traceback server-side; format_error
            # deliberately does not put the message in the client's reply.
            logger.exception("df_search failed")
            return format_error(exc)
        return format_search_results(result)

    @mcp.tool(
        name="df_get_charter",
        tags={"kansallisarkisto", "diplomatarium-fennicum", "charters"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Fetch one Diplomatarium Fennicum charter by its DF number — the citable identifier "
            "shown on every df_search hit — and return its full transcript plus dating, place of "
            "issue, language and index term. Use it after df_search to read a hit in full instead "
            "of its snippet. The transcript is machine-recognised text, so verify quotations "
            "against the source. Example: df_get_charter(df_number=1451)."
        ),
    )
    def df_get_charter(
        df_number: Annotated[int, Field(description="The DF number, e.g. 1451 for 'DF 1451'. This snapshot runs from 1 to 6888, with gaps.", ge=1)],
    ) -> str:
        try:
            record = get_search().get_charter(df_number)
        except MissingTableError as exc:
            return str(exc)
        except Exception as exc:
            logger.exception("df_get_charter failed")
            return format_error(exc)
        return format_charter(record, df_number)
