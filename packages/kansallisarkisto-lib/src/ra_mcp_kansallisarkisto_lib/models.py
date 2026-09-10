"""Pydantic models for the Sisältöhaku corpora.

``df`` (Diplomatarium Fennicum) and ``voudintilit`` (bailiff accounts) are modelled;
``tuomiokirjat`` follows the same shape and will land beside them.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from .astia import page_url

# Diplomatarium Fennicum is a scholarly edition, so its transcripts carry
# editorial apparatus inline: footnote markers as superscripts fused to the word
# they annotate ("Hundæbæth⁶", "Karulj²") and editorial insertions in square
# brackets, sometimes mid-word ("Fi[n]llandh"). A tokeniser has no reason to treat
# either as punctuation, so the indexed token becomes "hundæbæth⁶" and the plain
# word is unfindable. Measured on this corpus: 2,266 fused occurrences across 621
# records (14% of the transcribed ones), plus 4,801 bracketed forms across 1,969.
# Stripped from the search text only — `transcript` keeps the edition verbatim,
# because the apparatus is part of what a researcher is reading.
_FOOTNOTE_MARKS = re.compile(r"[\u2070-\u209f\u00b0\u00b2\u00b3\u00b9]+")
_EDITORIAL_BRACKETS = re.compile(r"[\[\]]")


def strip_editorial_apparatus(text: str) -> str:
    """Remove footnote superscripts and editorial brackets from text for indexing."""
    return _EDITORIAL_BRACKETS.sub("", _FOOTNOTE_MARKS.sub("", text))


# A year field of 0 in the source means "unknown", not year 0. Left as a literal 0
# it silently pollutes every date range — 6,843 of the 6,876 df records carry
# dating_end_year == 0 — so it is normalised to None on the way in.
UNKNOWN_YEAR = 0


def _clean(value: Any) -> str:
    """Coerce a source value to a stripped string; None becomes ""."""
    if value is None:
        return ""
    return str(value).strip()


def _year(value: Any) -> int | None:
    """Coerce a source year to int, mapping the sentinel 0 (and blanks) to None."""
    if value in (None, "", UNKNOWN_YEAR):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return None if year == UNKNOWN_YEAR else year


class DfRecord(BaseModel):
    """One Diplomatarium Fennicum charter — a medieval document concerning Finland.

    Field names follow the source JSON, so a record can be traced back to the
    Sisältöhaku export line it came from. Four columns are derived and carry no
    source counterpart: ``df_number``, ``year_from`` / ``year_to`` and
    ``searchable_text``; each is documented at the point it is built.
    """

    model_config = ConfigDict(populate_by_name=True)

    object_id: str
    df: str = ""
    # Derived: `df` is the citable charter number and is numeric for all 6,876
    # records, but as a string "10" sorts before "2". The int form is what a
    # range filter or an ordering can use; the string stays authoritative for
    # citation.
    df_number: int | None = None
    transcript: str = ""
    indexterm: str = ""
    issuingplace: str = ""
    issuingplacecountry: str = ""
    language: str = ""
    dating_start_year: int | None = None
    dating_end_year: int | None = None
    # Derived: the dating interval with the unknowns closed, so a date filter is a
    # plain two-column overlap test (`year_from <= max AND year_to >= min`)
    # instead of a COALESCE over nullable columns. A charter dated to a single
    # year has year_from == year_to. Both are None only when the source gives no
    # start year at all (22 records).
    year_from: int | None = None
    year_to: int | None = None
    lat: float | None = None
    lng: float | None = None

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> DfRecord:
        """Build a record from one line of ``df.jsonl.gz``.

        ``_geoloc`` is flattened to ``lat`` / ``lng``: the source nests them and
        sets both to null together (never one alone) for the 2,734 unlocated
        charters, which flat nullable columns represent exactly while being
        filterable.

        Every field is read defensively. The ingest reports a bad line by raising
        ``ValueError``/``TypeError`` and skipping it, so anything this method can
        raise outside those two — an ``AttributeError`` from a ``_geoloc`` that is
        a string rather than an object, say — would abort a 7.8M-line run over a
        single malformed record instead.
        """
        raw_geo = row.get("_geoloc")
        geo = raw_geo if isinstance(raw_geo, dict) else {}
        start = _year(row.get("dating_start_year"))
        end = _year(row.get("dating_end_year"))
        df = _clean(row.get("df"))

        return cls(
            object_id=_clean(row.get("objectID")),
            df=df,
            df_number=int(df) if df.isdigit() else None,
            transcript=_clean(row.get("transcript")),
            indexterm=_clean(row.get("indexterm")),
            issuingplace=_clean(row.get("issuingplace")),
            issuingplacecountry=_clean(row.get("issuingplacecountry")),
            language=_clean(row.get("language")),
            dating_start_year=start,
            dating_end_year=end,
            # An absent end year means the charter is dated to its start year, not
            # that it extends indefinitely; an absent start year with a known end
            # is treated symmetrically.
            year_from=start if start is not None else end,
            year_to=end if end is not None else start,
            lat=geo.get("lat"),
            lng=geo.get("lng"),
        )

    @property
    def searchable_text(self) -> str:
        """The text the full-text index is built over.

        Deliberately more than the transcript: 2,464 of the 6,876 df records
        (36%) are catalogued but untranscribed, and an index over ``transcript``
        alone would make them unreachable by search even though they are perfectly
        findable by place, index term or language. Folding the catalogue fields in
        keeps them in the result set.
        """
        parts = [
            # The citation itself, so that every record is reachable by *some*
            # keyword. Four charters carry no transcript, place, index term or
            # language at all, and were findable only if you already knew their
            # number. Written as "df <number>" rather than a fused token so the
            # way a researcher actually types it — "DF 404" — matches both terms.
            f"df {self.df}" if self.df else "",
            strip_editorial_apparatus(self.transcript),
            self.issuingplace,
            self.issuingplacecountry,
            self.indexterm,
            self.language,
        ]
        return " ".join(p for p in parts if p)


class VoudintilitRecord(BaseModel):
    """One page of a bailiff's account book — the Häme and Satakunta accounts, 1539–1635.

    A record is a page, not a document: the source's ``ay_id`` is the volume (one
    account book for one year) and ``file_id`` the page within it. Columns are named in
    English rather than after the source (``arkistoyksikkö``, ``aineistokokonaisuus``):
    LanceDB filter predicates name their columns bare, and a non-ASCII identifier is not
    one to trust its parser with. The mapping is in the docs' corpus reference.

    Joined at ingest with the volume's line from the Astia snapshot
    (:mod:`ra_mcp_kansallisarkisto_lib.astia`), which supplies what the export lacks: the
    archival reference, the series, and each page's viewer link.
    """

    page_id: str
    volume_id: int
    # Derived: the page number `file_id` spells as a zero-padded string ("0016").
    page: int | None = None
    file_id: str = ""
    collection: str = ""
    account_book: str = ""
    reference: str = ""
    series: str = ""
    year_start: int | None = None
    year_end: int | None = None
    # Derived: the year interval with the unknowns closed, as for df, so a date filter is
    # a two-column overlap test.
    year_from: int | None = None
    year_to: int | None = None
    text: str = ""
    url: str = ""

    @classmethod
    def from_json(cls, row: dict[str, Any], volume: dict[str, Any] | None) -> VoudintilitRecord:
        """Build a page from one line of ``voudintilit.jsonl.gz`` and its volume's Astia entry.

        ``volume`` is ``None`` when the snapshot has no entry for the volume; the page is
        then kept, without a reference or a link. As for df, only ``ValueError`` and
        ``TypeError`` may escape — a missing ``ay_id`` becomes ``int(None)``, a
        ``TypeError`` the ingest skips the line on, rather than a ``KeyError`` that would
        abort the run.
        """
        volume = volume or {}
        volume_id = int(row.get("ay_id"))  # ty: ignore[invalid-argument-type]
        file_id = _clean(row.get("file_id"))
        page = int(file_id) if file_id.isdigit() else None
        astia_file = (volume.get("files") or {}).get(page) if page is not None else None

        start, end = _year(row.get("alkuvuosi")), _year(row.get("loppuvuosi"))
        low, high = start, end
        if low is not None and high is not None and high < low:
            # One volume reads 1615–1516, in Astia's own catalogue too. The end year
            # precedes the corpus, so the start is the one to trust; widening to the
            # span would put its pages in every century's results.
            high = low

        return cls(
            page_id=_clean(row.get("objectID")),
            volume_id=volume_id,
            page=page,
            file_id=file_id,
            # The export leaves the Satakunta catalogue volume untitled; Astia names it.
            collection=_clean(row.get("aineistokokonaisuus")) or _clean(volume.get("fonds")),
            account_book=_clean(row.get("arkistoyksikkö")) or _clean(volume.get("title")),
            reference=_clean(volume.get("reference")),
            series=_clean(volume.get("series")),
            year_start=start,
            year_end=end,
            year_from=low if low is not None else high,
            year_to=high if high is not None else low,
            text=_clean(row.get("teksti")),
            url=page_url(volume_id, astia_file) if astia_file else "",
        )

    @property
    def searchable_text(self) -> str:
        """The text the full-text index is built over: the page, its account book and
        collection — the same three fields Sisältöhaku's own search covers."""
        return " ".join(p for p in (self.text, self.account_book, self.collection) if p)
