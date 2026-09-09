"""FastMCP server definition — opens the LanceDB tables and registers the tools."""

from __future__ import annotations

from fastmcp import FastMCP

from ra_mcp_kansallisarkisto_lib.config import DF_TABLE
from ra_mcp_kansallisarkisto_lib.dataset import get_lancedb, table_names
from ra_mcp_kansallisarkisto_lib.search_operations import DfSearch
from ra_mcp_kansallisarkisto_mcp.df_tool import register_df_tools
from ra_mcp_kansallisarkisto_mcp.errors import MISSING_TABLE, MissingTableError
from ra_mcp_kansallisarkisto_mcp.routes import register_routes
from ra_mcp_kansallisarkisto_mcp.settings import settings

kansallisarkisto_mcp: FastMCP = FastMCP(
    name="ra-kansallisarkisto-mcp",
    instructions=(
        "Full-text search over the Kansallisarkisto (National Archives of Finland) Sisältöhaku "
        "corpora — machine-transcribed archival text. Currently serving Diplomatarium Fennicum "
        "(`df`): 6,876 medieval charters concerning Finland, 859–1530. "
        "THE TEXT IS NOT IN FINNISH. Finland was part of the Swedish realm until 1809, and these "
        "documents are in early-modern Swedish, Latin and German. Search in the source language "
        "and in period spelling — 'bref' not 'brev', 'konung' not 'kung', 'Åbo' not 'Turku'. Only "
        "the catalogue metadata (language labels, countries, index terms) is Finnish, and its "
        "language labels are unaccented: 'venaja', never 'venäjä'. "
        "WORKFLOW: (1) `df_search` with a source-language term, narrowing by issuingplace, "
        "language, country or a year range; paginate with offset. (2) `df_get_charter` with the DF "
        "number from a hit to read the full transcript. "
        'Several words in a keyword must all appear, and a "quoted phrase" must appear exactly. '
        "AND, OR and NOT are not operators — they are searched for as ordinary words — so widen by "
        "removing a word or passing match_all=false, never by writing OR. "
        "Spelling was never standardised, and that is the usual reason a search looks empty: "
        "'bref' and 'breff' are the same word yet share only 71 of their 2,104 charters. When a "
        "result set looks thin, retry with fuzzy=1 on a base form before concluding the archive "
        "has nothing. "
        "Cite the DF number — it is the identifier a researcher quotes and the only stable handle "
        "on a charter. Reply to the user in the user's own language, but reproduce DF numbers, "
        "place names and language labels verbatim: they are what the user cites and what you pass "
        "back as filters. "
        "Two properties of the data change how results should be read: 36% of the charters are "
        "catalogued but never transcribed, so an empty transcript means 'not transcribed', not "
        "'nothing there'; and the transcripts are OCR/HTR output over a millennium of handwriting, "
        "so quotations should be checked against the archive rather than presented as exact."
    ),
)

_search: DfSearch | None = None


def get_search() -> DfSearch:
    """Return the process-wide DfSearch, built on first use from the configured URI.

    Built lazily, not at import: the server must boot without the table so the
    tools can report a missing one as a message instead of crashing the process —
    the image ships without data, and the table is mounted or ingested separately.
    """
    global _search
    if _search is None:
        db = get_lancedb(settings.lancedb_uri)
        if DF_TABLE not in table_names(db):
            raise MissingTableError(MISSING_TABLE)
        _search = DfSearch(db)
    return _search


register_df_tools(kansallisarkisto_mcp, get_search)
register_routes(kansallisarkisto_mcp)
