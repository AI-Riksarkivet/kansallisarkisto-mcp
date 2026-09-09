"""Where the LanceDB tables live, what they are called, and the paging bounds.

Resolution order for the LanceDB URI:

1. ``KA_LANCEDB_URI`` — an explicit override (any URI lancedb accepts, including
   ``s3://`` / ``gs://``).
2. ``<project root>/data``, **if it exists** — the local development location,
   which is what ``make ingest-df`` writes and what ``.gitignore`` excludes.
3. ``/data`` — the container mount point.
4. ``<project root>/data`` even though it does not exist — so a clone that has
   not been ingested yet names the path the user needs to create, rather than
   pointing at a ``/data`` they were never going to have.

The existence check in step 2 is load-bearing. The Docker image copies the whole
workspace to ``/app`` and installs the packages editable, so the project-root walk
finds ``/app`` inside the container too — without the check, an image whose
``KA_LANCEDB_URI`` was unset would look in ``/app/data`` and never at the mount.
"""

from __future__ import annotations

import os
from pathlib import Path

# One LanceDB database holds one table per corpus, so a single URI covers all
# three and each table can be built and shipped independently. voudintilit and
# tuomiokirjat get their names here when they get an ingest.
DF_TABLE = "df"

MOUNT_DIR = Path("/data")

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def _project_root() -> Path | None:
    """Walk up from this file to the workspace root (has pyproject.toml + packages/)."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pyproject.toml").exists() and (current / "packages").exists():
            return current
        current = current.parent
    return None


def resolve_lancedb_uri() -> str:
    """Return the LanceDB URI per the order documented in the module docstring.

    Resolved at call time rather than import time so a test or a container can set
    ``KA_LANCEDB_URI`` after the module is imported and still be honoured.
    """
    override = os.environ.get("KA_LANCEDB_URI", "").strip()
    if override:
        return override

    root = _project_root()
    local = root / "data" if root is not None else None
    if local is not None and local.is_dir():
        return str(local)
    if MOUNT_DIR.is_dir():
        return str(MOUNT_DIR)
    return str(local) if local is not None else str(MOUNT_DIR)
