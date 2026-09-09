"""The one failure the tools have to explain rather than log.

Lives in its own module so both `tools` (which raises it while building the
search facade) and `df_tool` (which catches it to answer with the explanation)
can import it without a cycle.
"""

from __future__ import annotations

MISSING_TABLE = (
    "The df table is not available on this server. It is built from the harvested Sisältöhaku export with `make ingest-df`, and mounted at KA_LANCEDB_URI; until then no charter search can run."
)


class MissingTableError(RuntimeError):
    """The LanceDB table this server serves has not been built at the configured URI.

    Distinct from an unexpected failure: it is a deployment state the operator can
    fix, and the tools say so in full rather than returning the generic internal
    error. The server boots without the table on purpose — the image ships empty.
    """
