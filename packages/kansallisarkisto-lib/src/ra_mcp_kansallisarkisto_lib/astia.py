"""Astia, Kansallisarkisto's digital archive: the page links and references voudintilit lacks.

The Sisältöhaku export gives each voudintilit page its volume (``ay_id``) and page number
(``file_id``) and nothing else — no link to the image, no archival reference. Astia's
public viewer loads both from two JSON endpoints, and this module reads their responses:

- ``json_tiedot.php?tyyppi=aineisto&id=<volume>`` — the volume's reference
  (``tunnisteet``), title, dates, and its place in the hierarchy (fonds, series);
- ``json_tiedostot.php?id=<volume>`` — every image in the volume, titled ``Tiedosto N``,
  with the Astia file id the viewer addresses it by. Page N is ``Tiedosto N``.

They are fetched once per volume at harvest time (``scripts/fetch_astia.py``) into a JSONL
snapshot, never while serving: the endpoints are undocumented, and a serving path that
depended on them would inherit every change Astia makes to them.
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ASTIA_URL = "https://astia.narc.fi/uusiastia/"
METADATA_URL = ASTIA_URL + "ws/json/json_tiedot.php?tyyppi=aineisto&id={volume_id}"
FILES_URL = ASTIA_URL + "ws/json/json_tiedostot.php?id={volume_id}"

_PAGE_NUMBER = re.compile(r"(\d+)\s*$")


def _label(value: Any) -> str:
    """An Astia label as plain text: entities unescaped, whitespace normalised."""
    return " ".join(html.unescape(str(value or "")).split())


def _children(node: Any) -> dict[str, str]:
    """Flatten one of Astia's XML-as-JSON nodes to ``{child name: tagData}``."""
    if not isinstance(node, dict):
        return {}
    return {child.get("name"): child["tagData"] for child in node.get("children") or [] if isinstance(child, dict) and child.get("tagData") is not None}


def parse_files(payload: dict[str, Any]) -> dict[int, str]:
    """Map page number to Astia file id, from a ``json_tiedostot`` response.

    An image without a numbered title (a cover, say) or without an id is not a page the
    export can refer to, and is skipped.
    """
    pages: dict[int, str] = {}
    for thumb in payload.get("thumbs") or []:
        fields = _children(thumb)
        number = _PAGE_NUMBER.search(fields.get("TITLE") or "")
        if number and fields.get("URL"):
            pages[int(number.group(1))] = str(fields["URL"])
    return pages


def parse_metadata(payload: dict[str, Any]) -> dict[str, str]:
    """The reference, title, dates, fonds and series, from a ``json_tiedot`` response.

    Astia HTML-escapes its labels (``tilej&#xE4;``), so they are unescaped here, and
    court-record series join their shelf prefix to the name with a non-breaking space
    (``a/1&#xA0;Porin raastuvanoikeuden tuomiokirjat``), so whitespace is normalised to
    single spaces. A date of ``-`` means there is none — the Satakunta catalogue volume
    is dated that way.
    """
    levels: dict[str, str] = {}
    for level in payload.get("ylemmat") or []:
        fields = _children(level)
        if fields.get("TASO"):
            levels[fields["TASO"]] = _label(fields.get("LABEL"))
    dates = str(payload.get("ajat") or "").strip()
    return {
        "reference": str(payload.get("tunnisteet") or "").strip(),
        "title": _label(payload.get("nimekkeet")),
        "dates": "" if dates == "-" else dates,
        "fonds": levels.get("fonds", ""),
        "series": levels.get("series", ""),
    }


def volume_entry(volume_id: int, metadata: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    """One snapshot line: a volume's metadata plus its page-to-file-id map."""
    return {
        "volume_id": volume_id,
        **parse_metadata(metadata),
        # JSON object keys are strings; load_snapshot turns them back into page numbers.
        "files": {str(page): file_id for page, file_id in parse_files(files).items()},
    }


def page_url(volume_id: int, file_id: str) -> str:
    """The Astia viewer, opened at one image of one volume."""
    return f"{ASTIA_URL}viewer/?fileId={file_id}&aineistoId={volume_id}"


def load_snapshot(path: str | Path) -> dict[int, dict[str, Any]]:
    """Read a snapshot written by ``scripts/fetch_astia.py``, keyed by volume id.

    A missing file is an empty snapshot rather than an error: the ingest still runs, and
    its pages simply carry no link or reference. A line that does not parse — the half
    line a fetch killed mid-write leaves behind — is skipped with a warning, so that
    volume is fetched again on resume instead of the whole file becoming unreadable.
    """
    path = Path(path)
    if not path.exists():
        return {}
    snapshot: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                entry["files"] = {int(page): file_id for page, file_id in (entry.get("files") or {}).items()}
                snapshot[int(entry["volume_id"])] = entry
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.warning("Skipping %s line %d: %s", path.name, lineno, exc)
    return snapshot
