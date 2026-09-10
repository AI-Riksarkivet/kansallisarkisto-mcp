"""The failures the tools have to explain rather than log — and the one place that
decides what every failure means, and writes the one log line every call gets.

Lives in its own module so `tools` (which raises MissingTableError while building a
search facade) and the tool modules (which answer with it) can share it without a cycle.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from ra_mcp_kansallisarkisto_lib.config import DEFAULT_LIMIT
from ra_mcp_kansallisarkisto_lib.dataset import SearchInputError, SearchResult
from ra_mcp_kansallisarkisto_lib.telemetry import mark_span_error, record_span_exception
from ra_mcp_kansallisarkisto_mcp.formatter import format_error

logger = logging.getLogger(__name__)

MISSING_TABLE = (
    "The df table is not available on this server. It is built from the harvested Sisältöhaku export with `make ingest-df`, and mounted at KA_LANCEDB_URI; until then no charter search can run."
)

MISSING_VOUDINTILIT_TABLE = (
    "The voudintilit table is not available on this server. It is built from the harvested Sisältöhaku export and the Astia snapshot "
    "with `make fetch-astia ingest-voudintilit`, and mounted at KA_LANCEDB_URI; until then no bailiff-account search can run."
)

MISSING_TUOMIOKIRJAT_TABLE = (
    "The tuomiokirjat table is not available on this server. It is built from the harvested Sisältöhaku export and the Astia snapshot "
    "with `make fetch-astia-tuomiokirjat ingest-tuomiokirjat`, and mounted at KA_LANCEDB_URI; until then no court-record search can run."
)


class MissingTableError(RuntimeError):
    """A LanceDB table this server serves has not been built at the configured URI.

    Distinct from an unexpected failure: it is a deployment state the operator can
    fix, and the tools say so in full rather than returning the generic internal
    error. The server boots without its tables on purpose — the image ships empty.
    """


# What a tool body hands back: the text for the client, and a few words for the log —
# "604 hits", "found" — that the text would be the wrong thing to parse for.
Answer = tuple[str, str]


def summary(result: SearchResult) -> str:
    """A search's outcome for the log: '1 hit', '604 hits', '10000+ hits'."""
    if result.total_is_capped:
        return f"{result.total_hits}+ hits"
    return f"{result.total_hits} hit{'' if result.total_hits == 1 else 's'}"


def found(record: Any) -> str:
    """A lookup's outcome for the log."""
    return "found" if record is not None else "not found"


def paging(offset: int, limit: int, match_all: bool, fuzzy: int) -> dict[str, Any]:
    """The paging and matching options a caller changed from their defaults — the ones
    worth a place in the log line; the defaults on every call would be noise."""
    return {
        **({"offset": offset} if offset else {}),
        **({"limit": limit} if limit != DEFAULT_LIMIT else {}),
        **({"match_all": match_all} if not match_all else {}),
        **({"fuzzy": fuzzy} if fuzzy else {}),
    }


def answer(tool: str, produce: Callable[[], Answer], **fields: Any) -> str:
    """Run a tool body, turning every failure into text the model can act on — and
    log one line for the call: the tool, what it was asked, what came of it, how long.

    Shared rather than repeated because the tools had already drifted once:
    `df_get_charter` was missing the `SearchInputError` branch. Formatting runs
    inside the try too, so nothing escapes as a protocol error.

    ``fields`` are the call's arguments as the caller named them; unset ones (None)
    are left out, so a line reads ``df_search keyword='konung' issuingplace='Åbo' ->
    49 hits in 118 ms`` rather than a row of ``=None``. The Space runs without OTel,
    so this line is the only record of a call there.
    """
    asked = " ".join(f"{name}={value!r}" for name, value in fields.items() if value is not None)
    start = time.perf_counter()

    def log(outcome: str) -> None:
        logger.info("%s %s -> %s in %d ms", tool, asked, outcome, (time.perf_counter() - start) * 1000)

    try:
        text, summary = produce()
    except MissingTableError as exc:
        # A deployment state the operator can fix, so it is explained in full.
        mark_span_error(str(exc), "missing_table")
        log("missing table")
        return str(exc)
    except SearchInputError as exc:
        # This library's own guards only — a blank keyword, a bad page, fuzzy on
        # a quoted phrase — so the message is written for the caller. Not
        # `except ValueError`: lancedb raises that too, and its messages quote
        # dataset paths a broad catch would hand to a public HTTP client.
        mark_span_error(str(exc), "validation")
        log(f"validation: {exc}")
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 - by design: nothing raises out to the client
        # record_span_exception keeps one failure to one traceback; the spine may
        # already have logged it. format_error keeps the message out of the reply.
        record_span_exception(logger, exc)
        mark_span_error(f"{tool} failed: {type(exc).__name__}")
        log(type(exc).__name__)
        return format_error(exc)
    log(summary)
    return text
