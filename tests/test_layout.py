# Copyright (c) 2026 MinchinWeb
"""Fitting rooms together into a house (``layout.py``)."""

from __future__ import annotations

import pytest

from custom_components.house_structure.layout import (
    Floor,
    Room,
    arrange,
    cost_of,
    fit,
    linked_across,
    outline_cells,
)


def _area(rect) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _hub() -> Floor:
    """A hall with a room on each side of it, and two of those side by side."""
    return Floor(
        rooms=[
            Room("hall", 8.0, long=True),
            Room("kitchen", 14.0, walls=(("S", 0.0), ("W", 0.0))),
            Room("living", 20.0, walls=(("S", 0.0), ("E", 0.0))),
            Room("bed", 12.0, walls=(("N", 0.0), ("E", 0.0))),
            Room("bath", 5.0, walls=(("N", 0.0),)),
            Room("office", 9.0, walls=(("N", 0.0), ("W", 0.0))),
        ],
        links=[
            ("hall", "kitchen", None),
            ("hall", "living", None),
            ("hall", "bed", None),
            ("hall", "bath", None),
            ("hall", "office", None),
            ("kitchen", "living", None),
            ("bath", "bed", None),
        ],
    )


def test_rooms_tile_a_rectangle_and_keep_their_areas():
    floor = _hub()
    placed = fit(floor)
    for room in floor.rooms:
        assert _area(placed[room.key]) == pytest.approx(room.area)
    west = min(r[0] for r in placed.values())
    east = max(r[2] for r in placed.values())
    south = min(r[1] for r in placed.values())
    north = max(r[3] for r in placed.values())
    # no gaps: the rectangle round the rooms is as big as the rooms
    assert (east - west) * (north - south) == pytest.approx(68.0)


def test_links_and_outside_walls_are_met():
    floor = _hub()
    faults = cost_of(floor, fit(floor))
    assert faults["links"] == 0
    assert faults["walls"] == pytest.approx(0, abs=0.5)


def test_a_link_is_on_the_face_it_names():
    floor = Floor(
        rooms=[Room("a", 12.0), Room("b", 12.0)],
        links=[("a", "b", "N")],  # b is on a's north face
    )
    placed = fit(floor)
    assert placed["b"][1] == pytest.approx(placed["a"][3])


def test_a_room_with_a_size_keeps_it_among_rooms_that_are_shaped():
    floor = Floor(
        rooms=[Room("a", 16.0), Room("bath", 3.0, size=(2.0, 1.5)), Room("c", 10.0)],
        links=[("a", "bath", None), ("a", "c", None)],
    )
    placed = fit(floor)
    bath = placed["bath"]
    assert (bath[2] - bath[0], bath[3] - bath[1]) == pytest.approx((2.0, 1.5))
    assert cost_of(floor, placed)["links"] == 0


def test_a_room_already_placed_is_left_alone_and_built_round():
    floor = Floor(
        rooms=[Room("a", 9.0), Room("b", 9.0)],
        fixed={"kitchen": (0.0, 0.0, 4.0, 3.0)},
        links=[("kitchen", "a", None), ("a", "b", None)],
    )
    placed = arrange([floor], [])
    assert placed["kitchen"] == (0.0, 0.0, 4.0, 3.0)
    faults = cost_of(floor, placed)
    assert faults["links"] == 0
    assert faults["overlap"] == 0


def test_an_upper_floor_goes_over_the_rooms_it_is_above():
    ground = Floor(
        rooms=[Room("living", 20.0), Room("kitchen", 12.0), Room("den", 12.0)],
        links=[("living", "kitchen", None), ("kitchen", "den", None)],
    )
    upper = Floor(rooms=[Room("bedroom", 10.0)])
    placed = arrange([ground, upper], [("den", "bedroom")])
    den, bedroom = placed["den"], placed["bedroom"]
    over = max(0.0, min(den[2], bedroom[2]) - max(den[0], bedroom[0])) * max(
        0.0, min(den[3], bedroom[3]) - max(den[1], bedroom[1])
    )
    assert over >= 0.5 * 10.0


def test_rooms_round_a_hole_are_linked_across_it():
    # a hallway nobody entered: the rooms round it open on to the same space
    hall = (4.0, 4.0, 6.0, 6.0)
    west, east = (0.0, 3.0, 4.0, 7.0), (6.0, 3.0, 10.0, 7.0)
    assert linked_across(west, east, [hall])
    assert not linked_across(west, east, [])
    assert not linked_across(west, (6.0, 8.0, 10.0, 12.0), [hall])


def test_the_same_floor_is_always_fitted_the_same():
    assert fit(_hub()) == fit(_hub())


def test_an_outline_is_cut_into_rectangles_as_big_as_the_rooms():
    # an L, 75 m² of a 10 by 10 square, to hold 48 m² of rooms
    outline = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
    cells, notches, width = outline_cells(outline, 48.0)
    assert sum(_area(c) for c in cells) == pytest.approx(48.0)
    assert width == pytest.approx(8.0)  # 10 m, shrunk by the square root of 48/75
    assert notches == pytest.approx([16.0])  # the missing quarter, shrunk too


def test_no_rooms_is_no_layout():
    assert fit(Floor(rooms=[])) == {}
    assert arrange([], []) == {}
