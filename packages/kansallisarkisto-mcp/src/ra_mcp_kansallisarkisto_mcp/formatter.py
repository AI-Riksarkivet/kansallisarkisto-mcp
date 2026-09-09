"""Render search results and errors as the plain text the model reads.

Every tool returns text rather than raising: an exception reaches the model as a
protocol error it cannot act on, whereas a sentence explaining that the table is
missing (or the range inverted) is something it can relay or correct.
"""

from __future__ import annotations

from typing import Any

from ra_mcp_kansallisarkisto_lib.dataset import SearchResult, format_results

# How much transcript to show per hit. Long enough to judge relevance, short
# enough that a 25-result page stays readable; the full text comes from
# df_get_charter.
SNIPPET_CHARS = 400


def _oneline(value: str) -> str:
    """Collapse a field to a single line before it goes into a result block.

    The output is a structured block that a model reads as a list of records, and
    the fields are interpolated into it. A newline inside one lets the field forge
    the structure around it — a fabricated "**DF 9999**" header, or a "More
    results available" footer — and the model has no way to tell the difference.
    No record in the current corpus contains one, but that is a property of this
    snapshot: the index is re-harvestable and grows, and the two larger corpora
    are millions of pages of OCR.

    The consequence is the one this project can least afford: a citation to a
    charter that does not exist.
    """
    return " ".join(value.split())


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " …"


def _dating(rec: dict[str, Any]) -> str:
    """Render the dating as the source states it, without inventing precision."""
    start, end = rec.get("dating_start_year"), rec.get("dating_end_year")
    if start is None and end is None:
        return "undated"
    if end is None:
        return str(start)
    if start is None:
        return f"by {end}"
    if start == end:
        return str(start)
    return f"{start}–{end}"


def _place(rec: dict[str, Any]) -> str:
    place = _oneline(rec.get("issuingplace") or "")
    country = _oneline(rec.get("issuingplacecountry") or "")
    if place and country:
        return f"{place}, {country}"
    return place or country or "place of issue unrecorded"


def _render_charter(rec: dict[str, Any], lines: list[str]) -> None:
    lines.append(f"**DF {_oneline(str(rec.get('df', '?')))}** — {_dating(rec)} — {_place(rec)}")
    details = [f"language: {_oneline(rec['language'])}" if rec.get("language") else "", f"index term: {_oneline(rec['indexterm'])}" if rec.get("indexterm") else ""]
    detail_line = " · ".join(d for d in details if d)
    if detail_line:
        lines.append(f"  {detail_line}")
    transcript = rec.get("transcript") or ""
    if transcript.strip():
        lines.append(f"  {_snippet(transcript)}")
    else:
        # 36% of the corpus. Say so, so the absence reads as "not transcribed"
        # rather than "search returned an empty record".
        lines.append("  (catalogued but not transcribed — no text available)")
    lines.append("")


def format_search_results(result: SearchResult) -> str:
    return format_results(result, label="Diplomatarium Fennicum", render_record=_render_charter)


def format_charter(rec: dict[str, Any] | None, df_number: str | int) -> str:
    """Render one charter in full — the whole transcript, not a snippet."""
    if rec is None:
        return f"No charter DF {df_number} in the Diplomatarium Fennicum corpus. Valid DF numbers in this snapshot run from 1 to 6888 (with gaps)."

    lines = [
        f"**DF {_oneline(str(rec.get('df', df_number)))}** — {_dating(rec)} — {_place(rec)}",
        "",
    ]
    if rec.get("language"):
        lines.append(f"Language: {_oneline(rec['language'])}")
    if rec.get("indexterm"):
        lines.append(f"Index term: {_oneline(rec['indexterm'])}")
    if rec.get("lat") is not None and rec.get("lng") is not None:
        # These locate the place of issue, not the events described.
        lines.append(f"Coordinates of the place of issue: {rec['lat']}, {rec['lng']}")
    lines.append("")

    transcript = (rec.get("transcript") or "").strip()
    if transcript:
        lines.append("Transcript:")
        lines.append(transcript)
    else:
        lines.append("This charter is catalogued but not transcribed; no text is available in this corpus.")
    return "\n".join(lines)


def format_error(exc: Exception) -> str:
    """Render an unexpected failure for the client.

    The exception *type* is kept — it is what lets a caller tell a transient
    failure from a permanent one — but its message is not. Every condition a
    caller could act on (blank keyword, inverted range, missing table) already
    has its own message, so anything reaching here is a server fault whose text
    would only disclose internals: lance errors quote the on-disk dataset path,
    which the server has no reason to hand to a public HTTP client. The full
    traceback is logged server-side by the handler that calls this.
    """
    return f"Error: the search failed with an internal {type(exc).__name__}. It has been logged; please report it if it persists."
