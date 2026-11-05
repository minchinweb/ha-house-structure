# Copyright (c) 2026 MinchinWeb
"""The sheet's text and the rooms' footprints, without Home Assistant."""

from __future__ import annotations

import pytest

from custom_components.house_structure.sheet import (
    COLUMNS,
    Footprint,
    dump,
    links,
    outside_faces,
    parse,
    shared_length,
)


def test_commas_and_tabs_both_read():
    comma = "kind,area_id,width\nroom,hall,120\n"
    tabs = "kind\tarea_id\twidth\nroom\thall\t120\n"
    assert (
        parse(comma)
        == parse(tabs)
        == [(1, {"kind": "room", "area_id": "hall", "width": "120"})]
    )


def test_blank_rows_are_skipped_and_short_rows_padded():
    text = "kind,area_id,width\n\nroom,hall\n,,\n"
    assert parse(text) == [(1, {"kind": "room", "area_id": "hall", "width": ""})]


def test_unknown_and_repeated_columns_are_refused():
    with pytest.raises(ValueError, match="unknown column 'colour'"):
        parse("kind,colour\nroom,red\n")
    with pytest.raises(ValueError, match="more than once"):
        parse("kind,kind\nroom,room\n")
    with pytest.raises(ValueError, match="kind column"):
        parse("area_id\nhall\n")


def test_a_row_with_extra_cells_is_refused():
    with pytest.raises(ValueError, match="row 1 has more cells"):
        parse("kind,area_id\nroom,hall,oops\n")


def test_dump_writes_the_columns_and_reads_back():
    rows = [{"id": "01", "kind": "room", "area_id": "Hall, north", "width": "12' 6\""}]
    text = dump(rows)
    assert text.splitlines()[0] == ",".join(COLUMNS)
    [(number, row)] = parse(text)
    assert number == 1
    assert row["area_id"] == "Hall, north"
    assert row["width"] == "12' 6\""


def _room(area: str, x: float, y: float, w: float, d: float, level: float = 0.0):
    return Footprint(area, x, y, w, d, level)


def test_rooms_sharing_an_edge_share_its_length():
    hall = _room("hall", 0, 0, 4, 3)
    kitchen = _room("kitchen", 4, 1, 3, 5)  # east of the hall, overlapping 2 m
    assert shared_length(hall, kitchen) == pytest.approx(2.0)
    assert shared_length(kitchen, hall) == pytest.approx(2.0)


def test_rooms_apart_or_on_another_floor_share_nothing():
    hall = _room("hall", 0, 0, 4, 3)
    apart = _room("apart", 5, 0, 3, 3)
    upstairs = _room("bed", 4, 0, 3, 3, level=2.7)
    assert shared_length(hall, apart) == 0
    assert shared_length(hall, upstairs) == 0


def test_beside_and_above_from_footprints():
    rooms = [
        _room("hall", 0, 0, 4, 3),
        _room("kitchen", 4, 0, 3, 3),
        _room("bed", 0, 0, 4, 3, level=2.7),
    ]
    beside, above = links(rooms)
    assert beside["hall"] == ["kitchen"]
    assert beside["kitchen"] == ["hall"]
    assert above["hall"] == ["bed"]
    assert above["kitchen"] == []


def test_outside_faces_leave_out_the_shared_side():
    hall = _room("hall", 0, 0, 4, 3)
    kitchen = _room("kitchen", 4, 0, 3, 3)
    faces = outside_faces(hall, [hall, kitchen])
    assert faces == {
        "N": pytest.approx(4.0),
        "S": pytest.approx(4.0),
        "W": pytest.approx(3.0),
    }
    assert faces.get("E") is None


def test_a_face_only_partly_shared_is_partly_outside():
    room = _room("room", 0, 0, 4, 4)
    neighbour = _room("other", 4, 2, 3, 4)  # shares 2 m of the east face
    assert outside_faces(room, [room, neighbour])["E"] == pytest.approx(2.0)


def test_feet_and_inch_marks_survive_both_delimiters():
    """A quote mark in a size is read as part of the cell, in a comma sheet, a tab
    sheet, and a tab sheet copied from a spreadsheet (which quotes such cells)."""
    comma = 'kind,width,height\nroom,12\' 6",6"\n'
    assert parse(comma) == [(1, {"kind": "room", "width": "12' 6\"", "height": '6"'})]
    tab = "kind\twidth\nroom\t12' 6\"\n"
    assert parse(tab) == [(1, {"kind": "room", "width": "12' 6\""})]
    copied = 'kind\twidth\nroom\t"12\' 6"""\n'
    assert parse(copied) == [(1, {"kind": "room", "width": "12' 6\""})]


def test_a_comma_decimal_is_refused_not_misread():
    """In a comma sheet, ``1,5 m`` has an extra cell, so the row is refused."""
    with pytest.raises(ValueError, match="more cells than the header"):
        parse("kind,width\nroom,1,5 m\n")
