# Copyright (c) 2026 MinchinWeb
"""Fitting rooms together into a house (``layout.py``)."""

from __future__ import annotations

import pytest

from custom_components.house_structure.layout import (
    Floor,
    N,
    Room,
    _contacts,
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
    # an L, 75 m² of a 10 by 10 square, to hold 66 m² of rooms
    outline = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
    cells, notches, width = outline_cells(outline, 66.0)
    assert sum(_area(c) for c in cells) == pytest.approx(66.0)
    assert width == pytest.approx(10 * (66 / 75) ** 0.5)  # shrunk to the rooms
    assert notches == pytest.approx([22.0])  # the missing quarter, shrunk too


def test_an_outline_much_bigger_than_the_rooms_keeps_its_size():
    # the same L for 48 m² of rooms: the rest is floor no room was given
    outline = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
    cells, notches, width = outline_cells(outline, 48.0)
    assert sum(_area(c) for c in cells) == pytest.approx(0.85 * 75)
    assert width == pytest.approx(10 * 0.85**0.5)
    # the missing quarter, and then what the rooms leave of the outline
    assert notches == pytest.approx([0.85 * 25, 0.85 * 75 - 48.0])


def test_a_smaller_floor_lines_up_with_the_floor_it_is_over():
    ground = Floor(
        rooms=[Room("living", 24.0), Room("kitchen", 16.0), Room("den", 16.0)],
        links=[("living", "kitchen", None), ("kitchen", "den", None)],
    )
    upper = Floor(
        rooms=[Room("bed", 20.0), Room("bath", 8.0), Room("study", 16.0)],
        links=[("bed", "bath", None), ("bath", "study", None)],
    )
    above = [("living", "bed"), ("kitchen", "bath"), ("den", "study")]
    placed = arrange([ground, upper], above)

    def sides(keys):
        rects = [placed[k] for k in keys]
        return [(min if k < 2 else max)(r[k] for r in rects) for k in range(4)]

    # 44 m² over 56: the same rectangle, with a hole for the rest
    assert sides(["bed", "bath", "study"]) == pytest.approx(
        sides(["living", "kitchen", "den"]), abs=0.01
    )


def test_rooms_shaped_to_fit_are_whole_steps_of_the_grid():
    inch = 0.0254
    floor = _hub()
    floor.rooms.append(Room("closet", 1.0, size=(1.0, 1.0)))
    floor.links.append(("closet", "bed", None))
    placed = arrange([floor], [], grid=inch)
    for room in floor.rooms:
        rect = placed[room.key]
        wide, deep = rect[2] - rect[0], rect[3] - rect[1]
        if room.size:  # keeps what was typed
            assert (wide, deep) == pytest.approx(room.size)
            continue
        for length in (wide, deep):
            assert length / inch == pytest.approx(round(length / inch), abs=1e-6)
        assert wide * deep == pytest.approx(room.area, rel=0.02)


def test_a_room_against_a_wing_is_against_its_room():
    # an L: the den is in the corner the living room's wing makes with it
    fixed = {
        "living": (0.0, 0.0, 6.0, 4.0),
        "living#wing": (0.0, 4.0, 2.0, 7.0),
        "bath": (2.0, 4.0, 6.0, 5.0),  # between the living room and the den
    }
    floor = Floor(
        rooms=[Room("den", 8.0, size=(4.0, 2.0))],
        fixed=fixed,
        links=[("living", "den", None)],
        wings={"living#wing": "living"},
    )
    placed = arrange([floor], [])
    # the only free place beside the living room is against its wing
    assert placed["den"] == pytest.approx((2.0, 5.0, 6.0, 7.0), abs=0.05)
    assert cost_of(floor, placed)["links"] == 0


def test_two_rooms_whose_wings_touch_are_against_each_other():
    fixed = {
        "a": (0.0, 0.0, 4.0, 3.0),
        "a#wing": (4.0, 0.0, 6.0, 1.0),
        "b#wing": (6.0, 0.0, 8.0, 1.0),
    }
    floor = Floor(
        rooms=[Room("b", 9.0, size=(3.0, 3.0))],
        fixed=fixed,
        links=[("a", "b", None), ("b", "b#wing", "W")],
        wings={"a#wing": "a", "b#wing": "b"},
    )
    placed = {**fixed, "b": (8.0, 0.0, 11.0, 3.0)}
    assert cost_of(floor, placed)["links"] == 0
    # without the wings, the same rooms are not linked
    floor.wings = {}
    assert cost_of(floor, placed)["links"] > 0


def test_no_rooms_is_no_layout():
    assert fit(Floor(rooms=[])) == {}
    assert arrange([], []) == {}


def test_a_mirror_takes_the_rectangle_of_its_partner_on_another_floor():
    # stairs on the lower floor, and their opening on the upper, where the
    # kitchen is fitted round it
    lower = Floor(rooms=[Room("stairs", 2.0, (1.0, 2.0))])
    upper = Floor(
        rooms=[Room("kitchen", 12.0, (4.0, 3.0)), Room("stairs#up", 2.0, (1.0, 2.0))]
    )
    mirror = [("stairs", "stairs#up")]
    placed = arrange([lower, upper], [], mirror=mirror)
    assert placed["stairs#up"] == placed["stairs"]
    assert _area(placed["stairs"]) == pytest.approx(2.0)
    k, s = placed["kitchen"], placed["stairs#up"]
    across = min(k[2], s[2]) - max(k[0], s[0])
    up = min(k[3], s[3]) - max(k[1], s[1])
    assert across <= 1e-9 or up <= 1e-9  # the kitchen does not overlap the opening


def test_rooms_measured_inside_are_a_wall_apart_and_keep_their_sizes():
    floor = Floor(
        rooms=[
            Room("a", 12.0, (4.0, 3.0), (("W", 0.0),)),
            Room("b", 9.0, (3.0, 3.0), (("E", 0.0),)),
        ],
        links=[("a", "b", "E")],
    )
    placed = arrange([floor], [], wall=0.1)
    a, b = placed["a"], placed["b"]
    assert (a[2] - a[0], a[3] - a[1]) == pytest.approx((4.0, 3.0))
    assert (b[2] - b[0], b[3] - b[1]) == pytest.approx((3.0, 3.0))
    assert b[0] - a[2] == pytest.approx(0.1)  # the wall between them


def test_a_wing_has_no_wall_against_its_room():
    floor = Floor(
        rooms=[Room("a", 12.0, (4.0, 3.0)), Room("a#wing", 2.0, (2.0, 1.0))],
        links=[("a", "a#wing", "N")],
        wings={"a#wing": "a"},
    )
    placed = arrange([floor], [], wall=0.1)
    a, wing = placed["a"], placed["a#wing"]
    assert wing[1] == pytest.approx(a[3])  # flush on the room's north face
    assert (wing[2] - wing[0], wing[3] - wing[1]) == pytest.approx((2.0, 1.0))


def test_a_room_placed_on_another_floor_leaves_the_outline_in_use():
    # an L: the south-east quarter of the square is missing
    outline = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
    cellar = Floor(rooms=[], fixed={"cellar": (1.0, 6.0, 4.0, 9.0)})
    ground = Floor(
        rooms=[Room("a", 25.0), Room("b", 25.0), Room("c", 25.0)],
        links=[("a", "b", None), ("b", "c", None)],
    )
    placed = arrange([cellar, ground], [], outline=outline)
    for key in "abc":
        _, y0, x1, _ = placed[key]
        assert not (x1 > 5.2 and y0 < 4.8), key  # nothing in the missing quarter


def test_a_pinwheel_of_rooms_that_keep_their_sizes_comes_out_as_built():
    # four rooms round a fifth, each against the next: no cut runs across
    # the house, so a slicing tree cannot make it; rooms put down where
    # their outside walls and links say do
    truth = {
        "a": ((0.0, 0.0, 4.0, 2.0), "SW"),
        "b": ((4.0, 0.0, 6.0, 4.0), "SE"),
        "c": ((2.0, 4.0, 6.0, 6.0), "NE"),
        "d": ((0.0, 2.0, 2.0, 6.0), "NW"),
        "e": ((2.0, 2.0, 4.0, 4.0), ""),
    }
    floor = Floor(
        rooms=[
            Room(
                key,
                _area(r),
                (r[2] - r[0], r[3] - r[1]),
                tuple((f, 0.0) for f in faces),
            )
            for key, (r, faces) in truth.items()
        ],
        links=[
            (a, b, None) for a, b in ("ab", "bc", "cd", "da", "ea", "eb", "ec", "ed")
        ],
    )
    placed = arrange([floor], [], outline=[(0, 0), (6, 0), (6, 6), (0, 6)])
    for key, (rect, _) in truth.items():
        assert placed[key] == pytest.approx(rect, abs=0.01), key


def test_rooms_one_over_the_other_that_overlap_by_a_hair_touch():
    _, pairs = _contacts([(0.0, 0.0, 2.0, 1.01), (0.0, 1.0, 2.0, 2.0)])
    assert pairs[(0, 1)] == (N, pytest.approx(2.0))
