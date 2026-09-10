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

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ra_mcp_kansallisarkisto_lib.config import DEFAULT_LIMIT, MAX_LIMIT
from ra_mcp_kansallisarkisto_lib.dataset import require_keyword, require_ordered_range
from ra_mcp_kansallisarkisto_lib.telemetry import mark_span_error
from ra_mcp_kansallisarkisto_mcp.errors import answer
from ra_mcp_kansallisarkisto_mcp.formatter import format_charter, format_search_results


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
            "surface it, and pass it to df_get_charter for the full transcript. Every DF number "
            "also resolves to https://df.kansallisarkisto.fi/document/<number>, the archives' own "
            "edition of that charter; give the user that link when citing one. "
            "The corpus is uneven across its range: 83% of it is 1400-1530 and barely 240 "
            "charters predate 1300, so a thin result for an early century is the archive, not the "
            "query. The text is machine-recognised, so check any quotation against the source. "
            'QUERY SYNTAX: several words means all of them must appear; "quote a phrase" to '
            "require the exact sequence; a trailing * is a prefix ('lepros*' finds leprosi, "
            "leprosorum, leprosis) and | lists alternatives ('reval*|reual*' finds either). "
            "Prefixes are how to search Latin and German, which are not stemmed — only Swedish "
            "is — and how to catch the spellings of a name. Do NOT write AND, OR or NOT — they "
            "are not operators here and are matched as ordinary words, so 'bref OR littera' "
            "also drags in every charter containing 'or'; write 'bref|littera'. To widen "
            "instead, drop a word or pass match_all=false. "
            "A PLACE IS TWO DIFFERENT QUESTIONS: issuingplace='Tallinn' finds charters ISSUED "
            "there, and leaves out the third of the corpus with no recorded place. Charters "
            "ABOUT a place say its period name in the text, so search that: "
            "df_search(keyword='lepros* reval*|reual*|revel*|reuel*|reffl*') is what finds the "
            "leper house at Reval. "
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
                    "and 'konungs'; accents are folded, so 'Abo' matches 'Åbo'. Latin and German are "
                    "NOT stemmed, so search them by prefix: a trailing * expands to every word form "
                    "that begins that way ('lepros*' — at least 3 characters before the *, at most "
                    "300 forms), and | separates alternatives within a term ('bref|breff', "
                    "'reval*|reual*'). Several words require all of them; "
                    '"quoted words" require that exact phrase. AND/OR/NOT are not '
                    "operators and will be searched for literally. "
                    "The catalogue fields are indexed alongside the transcript, so the Finnish index-term "
                    "vocabulary also works here even though it has no filter of its own: 'Piispat' "
                    "(bishops, 402), 'Kuninkaalliset' (royal, 542), 'Kaupungit' (towns, 1,171), "
                    "'Paavi' (pope and curia, 634), 'Kirjeet' (letters, 2,215), 'Asiakirjat' "
                    "(charters, 3,264). Combine one with a filter to narrow by kind and place at once."
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
                    "89), 'islanti' (4), 'muu' (other, 7). Note 'venaja', not 'venäjä' — the accented "
                    "form matches nothing. Matched exactly, with two consequences: 833 charters record "
                    "no language at all and are excluded whenever this is set, and 28 carry a compound "
                    "label such as 'latina, ruotsi' (15) or 'ruotsi, venaja' (3) which 'latina' alone "
                    "does not match — search the label as a keyword to catch those."
                )
            ),
        ] = None,
        issuingplace: Annotated[
            str | None,
            Field(
                description=(
                    "Place of issue, a case-insensitive substring over a vocabulary of 499 values. "
                    "THE NAMING IS MIXED: Finnish and Swedish places keep their historical Swedish form "
                    "— 'Åbo' (815, not Turku), 'Stockholm' (687), 'Viborg' (311, not Viipuri), "
                    "'Nådendal' (134), 'Raseborg' (120), 'Tavastehus' (43) — but places outside that "
                    "realm use their MODERN name: 'Tallinn' (197, NOT Reval), 'Gdansk' (37, NOT "
                    "Danzig), 'Tartu' (5, NOT Dorpat). The historical forms of those match nothing. "
                    "Also 'Rom' (364 — the substring also catches 'Magliano Romano'), 'Avignon' (96), "
                    "'Uppsala' (88), 'Lübeck' (42). THIS IS THE PLACE OF ISSUE, NOT THE SUBJECT: "
                    "2,314 charters (34%) record no place and are excluded whenever this is set, and "
                    "a charter about Tallinn written in Åbo is not issued at Tallinn. For charters "
                    "that mention a place, search its period spelling as a keyword prefix instead — "
                    "Tallinn is 'reval*|reual*|revel*|reuel*|reffl*', Gdansk 'dantz*|dantsk*', Tartu "
                    "'darpt*|darbt*|dorpt*|tarbat*'."
                )
            ),
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
                    "It is whole-word edit distance, so it does not reach inflections: 'lepros' with "
                    "fuzzy=2 misses 'leprosorum' and finds unrelated words instead — use a prefix "
                    "('lepros*') for that. "
                    'Cannot be combined with a "quoted phrase".'
                ),
                ge=0,
                le=2,
            ),
        ] = 0,
    ) -> str:
        # Every return below is a string, not an exception — which is right for the
        # model, but leaves FastMCP's tools/call span green on failure. mark_span_error
        # is what keeps the tool failure rate from reading as a flat zero.
        if err := require_keyword(keyword, "'konung' or 'littera'"):
            mark_span_error(err, "validation")
            return err
        if err := require_ordered_range(year_min, year_max, "year"):
            mark_span_error(err, "validation")
            return err
        return answer(
            "df_search",
            lambda: format_search_results(
                get_search().search(
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
            ),
        )

    @mcp.tool(
        name="df_get_charter",
        tags={"kansallisarkisto", "diplomatarium-fennicum", "charters"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        description=(
            "Fetch one Diplomatarium Fennicum charter by its DF number — the citable identifier "
            "shown on every df_search hit — and return its full transcript plus dating, place of "
            "issue, language and index term. Use it after df_search to read a hit in full instead "
            "of its snippet. The transcript is machine-recognised text, so verify quotations "
            "against the source: the charter's own page at "
            "https://df.kansallisarkisto.fi/document/<number> carries the printed-edition references "
            "(FMU, REA) and any images, and is the link to give the user. "
            "Example: df_get_charter(df_number=1451)."
        ),
    )
    def df_get_charter(
        df_number: Annotated[int, Field(description="The DF number, e.g. 1451 for 'DF 1451'. This snapshot runs from 1 to 6888, with gaps.", ge=1)],
    ) -> str:
        # A charter that does not exist is a normal answer, not a failure — the
        # span stays OK and the miss is recorded on the operations span instead.
        return answer("df_get_charter", lambda: format_charter(get_search().get_charter(df_number), df_number))
