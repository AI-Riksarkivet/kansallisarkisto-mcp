"""FastMCP server definition — opens the LanceDB tables and registers the tools."""

from __future__ import annotations

import threading

from fastmcp import FastMCP

from ra_mcp_kansallisarkisto_lib.config import DF_TABLE, VOUDINTILIT_TABLE
from ra_mcp_kansallisarkisto_lib.dataset import get_lancedb, table_names
from ra_mcp_kansallisarkisto_lib.search_operations import DfSearch, VoudintilitSearch
from ra_mcp_kansallisarkisto_mcp.df_tool import register_df_tools
from ra_mcp_kansallisarkisto_mcp.errors import MISSING_TABLE, MISSING_VOUDINTILIT_TABLE, MissingTableError
from ra_mcp_kansallisarkisto_mcp.routes import register_routes
from ra_mcp_kansallisarkisto_mcp.settings import settings
from ra_mcp_kansallisarkisto_mcp.voudintilit_tool import register_voudintilit_tools

kansallisarkisto_mcp: FastMCP = FastMCP(
    name="ra-kansallisarkisto-mcp",
    instructions=(
        "Full-text search over the Kansallisarkisto (National Archives of Finland) Sisältöhaku "
        "corpora — machine-transcribed archival text. Two corpora are served: Diplomatarium "
        "Fennicum (`df`), 6,876 medieval charters concerning Finland, 859–1530, through "
        "`df_search` and `df_get_charter`; and voudintilit, 98,945 pages of the Swedish crown's "
        "bailiff accounts for Häme and Satakunta, 1539–1635, through `voudintilit_search` and "
        "`voudintilit_get_page`. "
        "THE TEXT IS NOT IN FINNISH. Finland was part of the Swedish realm until 1809, and these "
        "documents are in early-modern Swedish, Latin and German. Search in the source language "
        "and in period spelling — 'bref' not 'brev', 'konung' not 'kung', 'Åbo' not 'Turku'. Only "
        "the catalogue metadata (language labels, countries, index terms) is Finnish, and its "
        "language labels are unaccented: 'venaja', never 'venäjä'. "
        "PLACE NAMES ARE MIXED, and this catches people out: Finnish and Swedish places carry "
        "their historical Swedish form ('Åbo' not 'Turku', 'Viborg' not 'Viipuri', 'Tavastehus', "
        "'Nådendal'), but places further afield carry their MODERN name — 'Tallinn' not 'Reval', "
        "'Gdansk' not 'Danzig', 'Tartu' not 'Dorpat'. The historical forms of those return "
        "nothing at all. "
        "WORKFLOW: (1) `df_search` with a source-language term, narrowing by issuingplace, "
        "language, country or a year range; paginate with offset. (2) `df_get_charter` with the DF "
        "number from a hit to read the full transcript. "
        "The index term is a controlled vocabulary of 75 values shaped 'Issuer, DocumentType' — "
        "issuers are Paikallishallinto (local administration, 1,783), Kaupungit (towns, 1,171), "
        "Yksityiset (private persons, 1,078), 'Paavi ja kuuria' (pope and curia, 634), "
        "Keskushallinto (central administration, 596), Kuninkaalliset (royal, 542), Piispat "
        "(bishops, 402), Kirkolliset, Monastiset; types are Asiakirjat (charters/documents, "
        "3,264), Kirjeet (letters, 2,215) and 'Tili- ja pöytäkirjamerkinnät' (account and "
        "protocol entries, 1,007). There is no filter for it, but it is indexed, so these words "
        "work as keywords: df_search(keyword='Piispat', issuingplace='Åbo') finds bishops' "
        "documents issued at Åbo. "
        'Several words in a keyword must all appear, and a "quoted phrase" must appear exactly. '
        "AND, OR and NOT are not operators — they are searched for as ordinary words — so widen by "
        "removing a word, writing alternatives as 'bref|breff', or passing match_all=false, never "
        "by writing OR. A trailing * is a prefix on the charters ('lepros*', which reaches the "
        "Latin and German the stemmer does not); the two page corpora are too large for one, so "
        "list spellings there, or use fuzzy=1. "
        "Spelling was never standardised, and that is the usual reason a search looks empty: "
        "'bref' and 'breff' are the same word yet share only 71 of their 2,104 charters. When a "
        "result set looks thin, retry with fuzzy=1 on a base form before concluding the archive "
        "has nothing. "
        "Cite the DF number — it is the identifier a researcher quotes and the only stable handle "
        "on a charter — and give the user its link: every DF number resolves to "
        "https://df.kansallisarkisto.fi/document/<number>, the National Archives' own edition of "
        "that charter, where the printed-edition references (FMU, REA) and any images sit. A DF "
        "number identifies the document as an informational entity, not one particular text "
        "version, so it stays valid across editions. Reply to the user in the user's own "
        "language, but reproduce DF numbers, place names and language labels verbatim: they are "
        "what the user cites and what you pass back as filters. "
        "Four properties of the data change how results should be read: 36% of the charters are "
        "catalogued but never transcribed, so an empty transcript means 'not transcribed', not "
        "'nothing there'; the transcripts are OCR/HTR output over a millennium of handwriting, so "
        "quotations should be checked against the archive rather than presented as exact; the "
        "catalogue metadata is itself openly incomplete, so an absent place or language means "
        "'not recorded' rather than 'none'; and the corpus is far from evenly spread across its "
        "859–1530 range — 83% of it falls in 1400–1530 and only about 240 charters predate 1300, "
        "so a thin result for an early century reflects the archive, not the search. "
        "VOUDINTILIT is paged, not documented: each hit is one page of an account book — a volume "
        "holding one bailiwick's accounts for one year. The pages are early-modern Swedish; only "
        "the collection and account-book titles are Finnish. Narrow `voudintilit_search` with "
        "collection ('hame' or 'satakunta'), account_book (a substring of the Finnish title, e.g. "
        "'Sääksmäen', 'Hämeen linnan') and a year range. Cite a page by what each hit leads with "
        "— reference number, account book, year and page, e.g. '2372 Ylä-Satakunnan tilikirja "
        "1585, p. 16' — and give the user its Astia link, which opens the page image in "
        "Kansallisarkisto's digital archive. Pass the page id to `voudintilit_get_page` for the "
        "full text and the ids of the previous and next pages: accounts continue across pages."
    ),
)

_search: DfSearch | None = None
# Tools run in a worker threadpool, so first use is genuinely concurrent: without
# this, 64 simultaneous first calls built 16 separate facades, each repeating the
# table listing. Harmless but not what "process-wide" claims.
_search_lock = threading.Lock()


def get_search() -> DfSearch:
    """Return the process-wide DfSearch, built on first use from the configured URI.

    Built lazily, not at import: the server must boot without the table so the
    tools can report a missing one as a message instead of crashing the process —
    the image ships without data, and the table is mounted or ingested separately.
    """
    global _search
    if _search is None:
        with _search_lock:
            if _search is None:
                db = get_lancedb(settings.lancedb_uri)
                if DF_TABLE not in table_names(db):
                    raise MissingTableError(MISSING_TABLE)
                _search = DfSearch(db)
    return _search


_voudintilit_search: VoudintilitSearch | None = None
_voudintilit_lock = threading.Lock()


def get_voudintilit_search() -> VoudintilitSearch:
    """Return the process-wide VoudintilitSearch — built lazily, as get_search is, so a
    missing voudintilit table is a tool message rather than a failed boot."""
    global _voudintilit_search
    if _voudintilit_search is None:
        with _voudintilit_lock:
            if _voudintilit_search is None:
                db = get_lancedb(settings.lancedb_uri)
                if VOUDINTILIT_TABLE not in table_names(db):
                    raise MissingTableError(MISSING_VOUDINTILIT_TABLE)
                _voudintilit_search = VoudintilitSearch(db)
    return _voudintilit_search


def readiness() -> tuple[bool, str]:
    """Whether the server can answer a search on every corpus, for the /ready probe.

    Goes through the same getters the tools use, so readiness and the tools agree by
    construction: if this says ready, no tool call will come back with the
    missing-table error. Every table has to be searchable — a server that can search
    df but not voudintilit answers half its tools with an error, which is exactly the
    state a readiness probe exists to keep traffic away from. Cheap after the first
    call, since the facades are cached, and it never raises: a probe that 500s tells an
    orchestrator less than one that reports "not ready" and why.
    """
    try:
        get_search()
        get_voudintilit_search()
    except MissingTableError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - a probe must answer, not raise
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"{DF_TABLE}, {VOUDINTILIT_TABLE}"


register_df_tools(kansallisarkisto_mcp, get_search)
register_voudintilit_tools(kansallisarkisto_mcp, get_voudintilit_search)
register_routes(kansallisarkisto_mcp, readiness)
