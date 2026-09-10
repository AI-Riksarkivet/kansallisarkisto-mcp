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

Staging (:func:`stage_lancedb`) is a separate, opt-in step on top of whatever this
resolves to: copying the tables onto local disk before serving them, for a host whose
mount lance cannot read reliably. The server decides whether to stage; this module
only knows how.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# One LanceDB database holds one table per corpus, so a single URI covers all
# three and each table can be built and shipped independently. tuomiokirjat gets
# its name here when it gets an ingest.
DF_TABLE = "df"
VOUDINTILIT_TABLE = "voudintilit"

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


def stage_lancedb(source: str, target: Path) -> str | None:
    """Copy the LanceDB database at ``source`` onto local disk at ``target``.

    Exists for Hugging Face Spaces, where the tables arrive on a Xet-backed FUSE mount
    that lance cannot query under load — its concurrent random reads fail with EIO (os
    error 5). One sequential copy at boot moves every query onto an ordinary filesystem;
    ra-mcp stages the same mount the same way.

    Returns the path to serve from, or ``None`` to serve ``source`` as it is: when it is
    object storage (lancedb reads that itself), when there is no populated directory to
    copy, or when anything about the copy fails — listing the mount included, since that
    is where the FUSE layer's EIO surfaces.

    A finished copy writes a marker, and only a marked target is reused, so a process
    restarted in the same container does not copy again. Anything else in the target is
    the fragment of a copy that was killed before its cleanup could run, and is cleared
    and redone rather than served: a partial table would look present and then fail
    every search. The marker, not a rename into place, is what signals completion,
    because the Space's target (``/data-local``) is created by root in a directory the
    runtime user cannot write to — it can be filled and emptied, never replaced.
    """
    if "://" in source:
        logger.info("Not staging %s: lancedb reads object storage itself", source)
        return None
    src = Path(source)
    try:
        if (target / _STAGED_MARKER).is_file():
            logger.info("Tables already staged at %s", target)
            return str(target)
        if not _is_populated(src):
            logger.info("Nothing to stage at %s — serving it as configured", src)
            return None
        _clear(target)
        logger.info("Staging %s -> %s ...", src, target)
        start = time.perf_counter()
        _copy_tree(src, target)
        (target / _STAGED_MARKER).touch()
    except OSError:
        logger.exception("Could not stage %s -> %s — serving %s directly", src, target, src)
        _clear(target)
        return None
    logger.info("Staged %s in %.1fs", target, time.perf_counter() - start)
    return str(target)


# Written into the target once a copy has finished; its absence marks a fragment.
_STAGED_MARKER = ".staged"


def _clear(path: Path) -> None:
    """Remove whatever is at ``path``. A directory whose parent is read-only — the
    Space's ``/data-local`` — is emptied and left in place rather than raising."""
    shutil.rmtree(path, ignore_errors=True)


def _is_populated(path: Path) -> bool:
    """True if ``path`` is a directory with at least one entry."""
    return path.is_dir() and any(path.iterdir())


def _copy_tree(source: Path, target: Path) -> None:
    """Copy the database directory: fresh directories, file contents only.

    Not ``shutil.copytree``, which stamps each source directory's mode onto its copy.
    The Space mounts its bucket read-only, so that made ``/data-local`` 0555 the moment
    the copy finished — the completion marker could not be written, the cleanup could
    not remove the copy, and the server fell back to serving the mount. Nothing about
    the mount's metadata is worth carrying over; the copies simply belong to the
    runtime user with its default modes. Split out so a test can make it fail part-way.
    """
    for dirpath, _dirnames, filenames in os.walk(source):
        relative = Path(dirpath).relative_to(source)
        (target / relative).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            shutil.copyfile(Path(dirpath) / name, target / relative / name)
