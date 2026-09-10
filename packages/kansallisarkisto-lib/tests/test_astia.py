"""Parsing Astia's volume endpoints into the snapshot that gives voudintilit pages a link.

The payloads are trimmed from the live responses for volume 1578628789, Ylä-Satakunnan
tilikirja 1585 — the shapes, including the HTML entities, are Astia's own.
"""

from __future__ import annotations

import json

from ra_mcp_kansallisarkisto_lib import astia

FILES = {
    "ocr-files": [],
    "thumbs": [
        {"name": "FILE", "attrs": [], "children": [{"name": "URL", "attrs": [], "tagData": "8489049740"}, {"name": "TITLE", "attrs": [], "tagData": "Tiedosto 1"}]},
        {"name": "FILE", "attrs": [], "children": [{"name": "URL", "attrs": [], "tagData": "8489049747"}, {"name": "TITLE", "attrs": [], "tagData": "Tiedosto 2"}]},
        {"name": "FILE", "attrs": [], "children": [{"name": "URL", "attrs": [], "tagData": "8489049974"}, {"name": "TITLE", "attrs": [], "tagData": "Tiedosto 40"}]},
    ],
    "fullres": [],
}

METADATA = {
    "tunnisteet": "2372",
    "nimekkeet": "Ylä-Satakunnan tilikirja",
    "tarkenne": "",
    "ajat": "xx.xx.1585-xx.xx.1585",
    "taso": "Arkistoyksikk&ouml;",
    "tyyppi": "aineisto",
    "ylemmat": [
        {
            "name": "AIN",
            "attrs": [],
            "children": [
                {"name": "ID", "attrs": [], "tagData": "1576083342"},
                {"name": "TASO", "attrs": [], "tagData": "fonds"},
                {"name": "LABEL", "attrs": [], "tagData": "Satakunnan voutikuntien tilej&#xE4;"},
            ],
        },
        {
            "name": "AIN",
            "attrs": [],
            "children": [
                {"name": "ID", "attrs": [], "tagData": "1576083763"},
                {"name": "TASO", "attrs": [], "tagData": "series"},
                {"name": "LABEL", "attrs": [], "tagData": "Asiakirjat"},
            ],
        },
    ],
}


def test_files_map_each_page_number_to_its_astia_file_id():
    """Page N of a volume is the image Astia titles 'Tiedosto N'."""
    assert astia.parse_files(FILES) == {1: "8489049740", 2: "8489049747", 40: "8489049974"}


def test_files_without_a_page_number_or_an_id_are_skipped():
    odd = {
        "thumbs": [
            {"name": "FILE", "children": [{"name": "TITLE", "tagData": "Tiedosto 3"}]},
            {"name": "FILE", "children": [{"name": "URL", "tagData": "99"}, {"name": "TITLE", "tagData": "Kansi"}]},
            "not an object",
        ]
    }
    assert astia.parse_files(odd) == {}


def test_files_tolerate_a_missing_image_list():
    assert astia.parse_files({}) == {}


def test_metadata_gives_the_reference_title_and_hierarchy():
    assert astia.parse_metadata(METADATA) == {
        "reference": "2372",
        "title": "Ylä-Satakunnan tilikirja",
        "dates": "xx.xx.1585-xx.xx.1585",
        "fonds": "Satakunnan voutikuntien tilejä",
        "series": "Asiakirjat",
    }


def test_metadata_normalises_the_whitespace_in_labels():
    """Court-record series arrive as 'a/1&#xA0;Porin raastuvanoikeuden tuomiokirjat' — the
    shelf prefix joined to the name by a non-breaking space, which would otherwise sit
    inside a citation and defeat any substring filter typed with an ordinary space."""
    payload = {
        **METADATA,
        "nimekkeet": " Tuomiokirjat  ",
        "ylemmat": [{"name": "AIN", "children": [{"name": "TASO", "tagData": "series"}, {"name": "LABEL", "tagData": "a/1&#xA0;Porin raastuvanoikeuden tuomiokirjat"}]}],
    }
    parsed = astia.parse_metadata(payload)
    assert parsed["series"] == "a/1 Porin raastuvanoikeuden tuomiokirjat"
    assert parsed["title"] == "Tuomiokirjat"


def test_metadata_tolerates_a_missing_hierarchy_and_blank_dates():
    """The catalogue volume, 1580560161, is dated '-'."""
    assert astia.parse_metadata({"tunnisteet": "103", "nimekkeet": "x", "ajat": "-"}) == {
        "reference": "103",
        "title": "x",
        "dates": "",
        "fonds": "",
        "series": "",
    }


def test_page_url_opens_the_viewer_at_that_image():
    assert astia.page_url(1578628789, "8489049755") == "https://astia.narc.fi/uusiastia/viewer/?fileId=8489049755&aineistoId=1578628789"


def test_snapshot_round_trips_through_jsonl(tmp_path):
    path = tmp_path / "astia.jsonl"
    path.write_text(json.dumps(astia.volume_entry(1578628789, METADATA, FILES), ensure_ascii=False) + "\n", encoding="utf-8")
    snapshot = astia.load_snapshot(path)
    assert snapshot[1578628789]["reference"] == "2372"
    assert snapshot[1578628789]["files"][40] == "8489049974"


def test_a_truncated_last_line_is_skipped_not_fatal(tmp_path):
    """A fetch killed mid-write leaves half a line behind; resuming, and ingesting, must
    both carry on past it rather than crash."""
    path = tmp_path / "astia.jsonl"
    whole = json.dumps(astia.volume_entry(1578628789, METADATA, FILES), ensure_ascii=False)
    path.write_text(whole + "\n" + whole[:40], encoding="utf-8")
    assert list(astia.load_snapshot(path)) == [1578628789]


def test_a_missing_snapshot_is_an_empty_one(tmp_path):
    """Ingest must still run without it: pages then carry no link or reference."""
    assert astia.load_snapshot(tmp_path / "absent.jsonl") == {}
