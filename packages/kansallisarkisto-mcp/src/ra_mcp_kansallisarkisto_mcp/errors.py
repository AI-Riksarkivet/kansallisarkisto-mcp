"""The failures the tools have to explain rather than log — and the one place that
decides what every failure means.

Lives in its own module so `tools` (which raises MissingTableError while building a
search facade) and the tool modules (which answer with it) can share it without a cycle.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ra_mcp_kansallisarkisto_lib.dataset import SearchInputError
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


def answer(tool: str, produce: Callable[[], str]) -> str:
    """Run a tool body, turning every failure into text the model can act on.

    Shared rather than repeated because the tools had already drifted once:
    `df_get_charter` was missing the `SearchInputError` branch. Formatting runs
    inside the try too, so nothing escapes as a protocol error.
    """
    try:
        return produce()
    except MissingTableError as exc:
        # A deployment state the operator can fix, so it is explained in full.
        mark_span_error(str(exc), "missing_table")
        return str(exc)
    except SearchInputError as exc:
        # This library's own guards only — a blank keyword, a bad page, fuzzy on
        # a quoted phrase — so the message is written for the caller. Not
        # `except ValueError`: lancedb raises that too, and its messages quote
        # dataset paths a broad catch would hand to a public HTTP client.
        mark_span_error(str(exc), "validation")
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 - by design: nothing raises out to the client
        # record_span_exception keeps one failure to one traceback; the spine may
        # already have logged it. format_error keeps the message out of the reply.
        record_span_exception(logger, exc)
        mark_span_error(f"{tool} failed: {type(exc).__name__}")
        return format_error(exc)
