# Copyright (c) 2026 MinchinWeb
"""The isometric drawings: a room, the house from its rooms, and the heating runs."""

from __future__ import annotations

import math

import pytest

from custom_components.house_structure.constants import (
    DOOR,
    INTERNAL_WALL,
    REGISTER,
    ROOM,
    WALL,
    WINDOW,
)
from custom_components.house_structure.drawing import (
    _box,
    _footprint,
    _north,
    _openings,
    _place,
    floor_lifts,
    house_svg,
    project,
    room_svg,
)
from custom_components.house_structure.geometry import FOOT
from custom_components.house_structure.model import Raw, build

HOUSE = {"rotation": 0.0, "unit": "m", "shade_below": 0.0}
FLOOR = 'fill="#f3efe6"'
WALL_FILL = 'fill="#e2d3ae"'
DASHED = 'stroke-dasharray="4 3"'


def _elements(*raws: Raw, house: dict = HOUSE):
    elements, problems = build(house, list(raws))
    assert problems == []
    return elements


def _room(area: str, **data) -> Raw:
    return Raw(f"room-{area}", ROOM, area.title(), {"area_id": area, **data})


def _wall(id_: str, area: str, face: str, **data) -> Raw:
    return Raw(
        id_,
        WALL,
        f"{face} wall",
        {"area_id": area, "face": face, "length_m": 4.0, "height_m": 2.4, **data},
    )


def _window(id_: str, host: str, **data) -> Raw:
    size = {"width_m": 1.0, "height_m": 1.2}
    return Raw(id_, WINDOW, "Window", {"host": host, **size, **data})


def _register(id_: str, area: str, **data) -> Raw:
    return Raw(
        id_,
        REGISTER,
        "Register",
        {"area_id": area, "climate": "climate.hall", **data},
    )


def test_east_runs_right_north_runs_left_and_height_is_up():
    east, north, up = project((1, 0, 0)), project((0, 1, 0)), project((0, 0, 1))
    assert east[0] > 0 > north[0]
    assert east[1] < 0 and north[1] < 0  # both recede, so both climb the page
    assert up[1] < 0 and up[0] == pytest.approx(0)


def test_a_room_with_four_walls_draws_a_floor_and_four_faces():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("n", "kitchen", "N"),
        _wall("e", "kitchen", "E"),
        _wall("s", "kitchen", "S"),
        _wall("w", "kitchen", "W"),
    )
    svg = room_svg(elements, HOUSE, "kitchen")
    assert svg.count(FLOOR) == 1
    assert svg.count(WALL_FILL) == 4
    assert svg.count(DASHED) == 0


def test_a_face_with_no_wall_part_is_dashed():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "hall", "S"),
    )
    svg = room_svg(elements, HOUSE, "hall")
    assert svg.count(WALL_FILL) == 1
    assert svg.count(DASHED) == 3
    assert "Dashed faces have no wall part yet: N, E, W." in svg


def test_a_window_is_centred_on_its_wall():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S"),
        _window("win", "s", width_m=1.0, height_m=1.2),
    )
    box = _box(elements["room-kitchen"], 0.0, 0.0, 0.0, "m")
    (glass,) = _openings(box, "S", [elements["win"]], [])
    xs = [x for x, _, _ in glass.points]
    assert min(xs) == pytest.approx(1.5)  # 4 m wall, 1 m glass: 1.5 to 2.5
    assert max(xs) == pytest.approx(2.5)


def test_a_room_with_only_a_floor_area_is_drawn_square():
    elements = _elements(_room("study", floor_m2=16.0))
    width, depth, notes = _footprint(elements["room-study"])
    assert (width, depth) == pytest.approx((4.0, 4.0))
    assert any("square" in note for note in notes)


def test_a_width_with_the_floor_area_gives_the_depth():
    elements = _elements(_room("study", width_m=4.0, floor_m2=12.0))
    width, depth, _ = _footprint(elements["room-study"])
    assert (width, depth) == pytest.approx((4.0, 3.0))


def test_a_room_with_no_size_is_noted_not_drawn():
    elements = _elements(_room("empty"))
    assert "no size yet" in room_svg(elements, HOUSE, "empty")
    assert room_svg(elements, HOUSE, "missing") is None


def test_rooms_without_a_position_go_in_a_row_after_the_placed_ones():
    elements = _elements(
        _room("placed", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _room("loose", width_m=2.0, depth_m=3.0),
    )
    boxes, notes = _place(elements, "m")
    loose = next(b for b in boxes if b.area == "loose")
    assert loose.x == pytest.approx(5.0)  # the placed room ends at 4 m, then a metre
    assert loose.y == pytest.approx(0.0)
    assert any("drawn in a row" in note for note in notes)


def test_a_floor_above_the_ground_sits_at_its_level():
    elements = _elements(
        _room("upstairs", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7)
    )
    (box,) = _place(elements, "m")[0]
    assert box.z == pytest.approx(2.7)


def test_a_run_goes_across_at_the_plenum_height_then_to_the_outlet():
    house = {**HOUSE, "plenum_x_m": 0.0, "plenum_y_m": 0.0, "plenum_z_m": 0.0}
    duct = [{"shape": "round", "diameter_in": 6.0, "length_ft": 14.0}]
    elements = _elements(
        _room("den", width_m=4.0, depth_m=2.0, x_m=10.0, y_m=0.0),
        _register("reg", "den", at_x_m=2.0, at_y_m=1.0, at_z_m=0.1, duct=duct),
        house=house,
    )
    svg = house_svg(elements, house)
    # straight across to (12, 1) on the plenum's level, then up 0.1 m to the outlet
    drawn = (math.hypot(12.0, 1.0) + 0.1) / FOOT
    assert f"run {drawn:.0f} ft drawn, duct 14 ft" in svg


def test_no_plenum_means_no_runs_and_says_so():
    elements = _elements(
        _room("den", width_m=4.0, depth_m=2.0, x_m=0.0, y_m=0.0),
        _register("reg", "den"),
    )
    svg = house_svg(elements, HOUSE)
    assert "Type the plenum's position" in svg
    assert "run " not in svg


def test_true_north_points_away_from_the_viewer_at_zero_rotation():
    straight_on = _north(0.0)
    assert straight_on[1] < 0  # up the page, away from the south-west viewer
    turned = _north(90.0)
    assert turned[1] > 0  # turned a quarter, north is now towards the viewer


def test_the_house_drawing_is_an_svg_with_a_north_arrow():
    elements = _elements(_room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0))
    svg = house_svg(elements, HOUSE)
    assert svg.startswith("<svg")
    assert ">N</text>" in svg


def test_the_model_reads_positions_footprints_and_glass_sizes():
    elements = _elements(
        _room("hall", width_m=3.5, depth_m=2.2, x_m=-1.0, y_m=4.0, level_m=2.7),
        _wall("s", "hall", "S"),
        _window("win", "s", width_m=0.8, height_m=1.1),
        _register("reg", "hall", at_x_m=0.5, at_y_m=0.4, at_z_m=0.15),
    )
    room = elements["room-hall"]
    assert (room.width_m, room.depth_m) == (3.5, 2.2)
    assert (room.x_m, room.y_m, room.level_m) == (-1.0, 4.0, 2.7)
    window = elements["win"]
    assert (window.glass_width_m, window.glass_height_m) == (0.8, 1.1)
    reg = elements["reg"]
    assert (reg.at_x_m, reg.at_y_m, reg.at_z_m) == (0.5, 0.4, 0.15)


DOOR_FILL = 'fill="#a8744a"'


def test_a_door_stands_on_the_floor_beside_the_windows():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S"),
        _window("win", "s", width_m=1.0, height_m=1.2),
        Raw("door", DOOR, "South door", {"host": "s", "width_m": 1.0, "height_m": 2.0}),
    )
    box = _box(elements["room-kitchen"], 0.0, 0.0, 0.0, "m")
    door, glass = _openings(box, "S", [elements["win"]], [elements["door"]])
    # a row of 2 m centred on the 4 m wall: the door from 1 to 2, the window 2 to 3
    assert [x for x, _, _ in door.points] == pytest.approx([1.0, 2.0, 2.0, 1.0])
    assert [z for _, _, z in door.points] == pytest.approx([0.0, 0.0, 2.0, 2.0])
    assert min(x for x, _, _ in glass.points) == pytest.approx(2.0)
    assert room_svg(elements, HOUSE, "kitchen").count(DOOR_FILL) == 1


def _two_rooms(**hall):
    return (
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4, x_m=0.0, y_m=0.0),
        _room("hall", width_m=2.0, depth_m=3.0, height_m=2.4, **hall),
        Raw(
            "int",
            INTERNAL_WALL,
            "Wall to hall",
            {"area_id": "kitchen", "other_area_id": "hall"},
        ),
        Raw("door", DOOR, "Door to hall", {"host": "int"}),
    )


def test_an_inside_door_is_drawn_on_the_shared_face():
    # the hall is east of the kitchen, so the door is on the kitchen's east face
    elements = _elements(*_two_rooms(x_m=4.0, y_m=1.0))
    svg = room_svg(elements, HOUSE, "kitchen")
    assert svg.count(DOOR_FILL) == 1
    house = house_svg(elements, HOUSE)
    assert house.count(DOOR_FILL) == 1  # drawn once, from the wall's own room


def test_an_inside_door_without_positions_is_listed_instead():
    elements = _elements(*_two_rooms())
    svg = room_svg(elements, HOUSE, "kitchen")
    assert DOOR_FILL not in svg
    assert "Door to hall: not drawn; type both rooms" in svg
    elements = _elements(*_two_rooms(x_m=9.0, y_m=0.0))
    assert "do not touch" in room_svg(elements, HOUSE, "kitchen")


def test_floors_drawn_apart_lift_each_floor_above_the_one_below():
    elements = _elements(
        _room("rec", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=-2.4),
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        # a split level's half flight up is still the main floor
        _room("den", width_m=3.0, depth_m=3.0, x_m=4.0, y_m=0.0, level_m=0.2),
        _room("landing", width_m=2.0, depth_m=2.0, x_m=7.0, y_m=0.0, level_m=1.0),
        _room("office", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
    )
    boxes, _ = _place(elements, "m")
    assert floor_lifts(boxes, gap=2.5) == [(-2.4, 0.0), (0.0, 2.5), (2.7, 5.0)]


def test_more_than_three_and_a_half_feet_up_is_another_floor():
    elements = _elements(
        _room("main", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("half", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0, level_m=1.06),
        _room("loft", width_m=4.0, depth_m=3.0, x_m=8.0, y_m=0.0, level_m=1.08),
    )
    boxes, _ = _place(elements, "m")
    # 3 1/2 ft is 1.067 m: the half level stays, the loft starts a floor
    assert floor_lifts(boxes, gap=2.5) == [(0.0, 0.0), (1.08, 2.5)]


def test_floors_drawn_apart_keep_the_real_run_lengths():
    house = {**HOUSE, "plenum_x_m": 0.0, "plenum_y_m": 0.0, "plenum_z_m": -2.0}
    elements = _elements(
        _room("rec", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=-2.4),
        _room("office", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
        _register("reg", "office", at_x_m=3.0, at_y_m=0.0, at_z_m=0.0),
        house=house,
    )
    together = house_svg(elements, house)
    apart = house_svg(elements, house, exploded=True)
    drawn = (3.0 + 4.7) / FOOT  # across 3 m, then up from -2.0 to 2.7
    assert f"run {drawn:.0f} ft drawn" in together
    assert f"run {drawn:.0f} ft drawn" in apart
    assert "Floors drawn apart" in apart
    assert "Floors drawn apart" not in together
    assert apart != together


def test_one_floor_draws_the_same_apart_or_together():
    elements = _elements(_room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0))
    assert house_svg(elements, HOUSE, exploded=True) == house_svg(elements, HOUSE)
