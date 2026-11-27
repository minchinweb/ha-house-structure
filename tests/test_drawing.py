# Copyright (c) 2026 MinchinWeb
"""The isometric drawings: a room, the house from its rooms, and the heating runs."""

from __future__ import annotations

from dataclasses import replace
import math
import re

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
    _PLACED,
    IMPLIED_DASH,
    LARGE_TEXT,
    OPEN_DASH,
    OPENING_FILL,
    OPENING_GAP,
    SLAB,
    Scene,
    _add_connections,
    _box,
    _clear_shift,
    _door_size,
    _floor_index,
    _floor_shifts,
    _footprint,
    _gaps,
    _inside_parts,
    _meet,
    _north,
    _openings,
    _parts,
    _place,
    _shared_face,
    _touching,
    _wall_stretches,
    _wing_parts,
    face_order,
    house_svg,
    near_faces,
    project,
    room_svg,
)
from custom_components.house_structure.geometry import FEET_INCHES, FOOT
from custom_components.house_structure.model import Element, Raw, build

HOUSE = {"rotation": 0.0, "unit": "m", "shade_below": 0.0}
FLOOR = 'fill="#f3efe6"'
WALL_FILL = 'fill="#e2d3ae"'
INSIDE_FILL = 'fill="#cfdcd6"'  # a wall between two rooms
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


def _apart(a, b) -> bool:
    """Whether two boxes take up none of the same floor."""
    return (
        min(a.x + a.width, b.x + b.width) - max(a.x, b.x) < 1e-6
        or min(a.y + a.depth, b.y + b.depth) - max(a.y, b.y) < 1e-6
    )


def _open_face(boxes, area: str, face: str) -> bool:
    """Whether no other room is against a room's face."""
    where = {b.area: b for b in boxes}
    here = where[area]
    return not any(
        (_shared_face(here, other) or ("",))[0] == face
        for other in boxes
        if other.area != area
    )


def test_a_room_without_a_position_goes_beside_the_placed_ones():
    elements = _elements(
        _room("placed", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _room("loose", width_m=2.0, depth_m=3.0),
    )
    boxes, notes = _place(elements, "m")
    where = {b.area: b for b in boxes}
    assert (where["placed"].x, where["placed"].y) == (0.0, 0.0)  # it stays put
    assert (where["loose"].width, where["loose"].depth) == (2.0, 3.0)
    assert _apart(where["placed"], where["loose"])
    assert any("no position typed" in note for note in notes)


def test_loose_rooms_keep_their_outside_walls_on_the_outside():
    elements = _elements(
        _room("ne", width_m=3.0, depth_m=3.0),
        _wall("ne_n", "ne", "N"),
        _wall("ne_e", "ne", "E"),
        _room("e", width_m=3.0, depth_m=3.0),
        _wall("e_e", "e", "E"),
        _room("se", width_m=3.0, depth_m=3.0),
        _wall("se_s", "se", "S"),
        _wall("se_e", "se", "E"),
        _room("w", width_m=3.0, depth_m=3.0),
        _wall("w_w", "w", "W"),
    )
    boxes, _ = _place(elements, "m")
    for area, face in (
        ("ne", "N"),
        ("ne", "E"),
        ("e", "E"),
        ("se", "S"),
        ("se", "E"),
        ("w", "W"),
    ):
        assert _open_face(boxes, area, face), f"{area} {face}"
    for a in boxes:
        for b in boxes:
            assert a is b or _apart(a, b)


def test_a_room_with_only_a_floor_area_is_shaped_to_fit_its_neighbours():
    # two rooms given by area alone fill a rectangle between them: no gap, no
    # ragged edge, and each keeps its floor area
    elements = _elements(
        _room("living", floor_m2=20.0, beside=["kitchen"]),
        _room("kitchen", floor_m2=12.0),
    )
    boxes, notes = _place(elements, "m")
    where = {b.area: b for b in boxes}
    living, kitchen = where["living"], where["kitchen"]
    # to the nearest centimetre each way, as a house in metres is built
    assert living.width * living.depth == pytest.approx(20.0, rel=0.005)
    assert kitchen.width * kitchen.depth == pytest.approx(12.0, rel=0.005)
    for size in (living.width, living.depth, kitchen.width, kitchen.depth):
        assert size * 100 == pytest.approx(round(size * 100), abs=1e-6)
    face, start, end = _shared_face(living, kitchen)
    # they share the whole of the face between them
    assert end - start == pytest.approx(
        living.width if face in ("N", "S") else living.depth
    )
    assert any("shaped to fit" in note for note in notes)


def test_a_room_with_a_width_and_depth_keeps_them():
    elements = _elements(
        _room("living", floor_m2=20.0, beside=["bath"]),
        _room("bath", width_m=2.0, depth_m=1.5),
    )
    boxes, _ = _place(elements, "m")
    bath = next(b for b in boxes if b.area == "bath")
    assert (bath.width, bath.depth) == (2.0, 1.5)


def test_the_same_house_is_always_placed_the_same():
    raws = (
        _room("living", floor_m2=20.0, beside=["kitchen", "hall"]),
        _room("kitchen", floor_m2=12.0, beside=["hall"]),
        _room("hall", floor_m2=6.0),
    )
    first, _ = _place(_elements(*raws), "m")
    _PLACED.clear()  # fitted again, not read back
    again, _ = _place(_elements(*raws), "m")
    assert first == again


def test_a_floor_with_no_heights_typed_sits_on_the_one_below():
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0, height_m=2.5),
        _room("upstairs", width_m=3.0, depth_m=3.0),
        _room("cellar", width_m=3.0, depth_m=3.0, height_m=2.0),
    )
    boxes, _ = _place(elements, "m", {"ground": 0, "upstairs": 1, "cellar": -1})
    at = {b.area: b for b in boxes}
    assert at["ground"].z == pytest.approx(0.0)
    assert at["upstairs"].z == pytest.approx(2.5 + SLAB)
    assert at["cellar"].z == pytest.approx(-2.0 - SLAB)


def test_a_room_sits_over_the_room_it_is_above():
    elements = _elements(
        _room("living", floor_m2=20.0, beside=["kitchen"]),
        _room("kitchen", floor_m2=12.0, above=["bedroom"]),
        _room("bedroom", floor_m2=9.0),
    )
    floors = {"living": 0, "kitchen": 0, "bedroom": 1}
    boxes, _ = _place(elements, "m", floors)
    at = {b.area: b for b in boxes}
    kitchen, bedroom = at["kitchen"], at["bedroom"]
    over_x = min(kitchen.x + kitchen.width, bedroom.x + bedroom.width) - max(
        kitchen.x, bedroom.x
    )
    over_y = min(kitchen.y + kitchen.depth, bedroom.y + bedroom.depth) - max(
        kitchen.y, bedroom.y
    )
    assert over_x > 0 and over_y > 0
    assert over_x * over_y >= 0.5 * 9.0  # most of the bedroom is over the kitchen


def test_the_biggest_floor_is_fitted_to_the_building_outline():
    # an L: the south-east quarter of the square is missing
    outline = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
    elements = _elements(
        _room("a", floor_m2=25.0, beside=["b"]),
        _room("b", floor_m2=25.0, beside=["c"]),
        _room("c", floor_m2=25.0),
    )
    boxes, _ = _place(elements, "m", outline=outline)
    # 75 m² of rooms in a 75 m² outline: nothing is in the missing quarter
    for box in boxes:
        in_notch = (box.x + box.width > 5.01) and (box.y < 4.99)
        assert not in_notch, box.area


def test_a_detached_building_is_set_beside_the_house():
    elements = _elements(
        _room("living", floor_m2=20.0, beside=["kitchen"]),
        _room("kitchen", floor_m2=12.0),
        _room("garage", width_m=6.0, depth_m=6.0),
    )
    boxes, _ = _place(elements, "m", buildings=[["garage"]])
    at = {b.area: b for b in boxes}
    house_east = max(b.x + b.width for b in boxes if b.area != "garage")
    assert at["garage"].x > house_east


def _house_and_garage(**spot):
    """A 10 by 6 m house and a 4 by 3 m garage, which sits as ``spot`` says."""
    elements = _elements(
        _room("living", width_m=10.0, depth_m=6.0),
        _room("garage", width_m=4.0, depth_m=3.0),
    )
    building = {"area_ids": ["garage"], **spot}
    boxes, _ = _place(elements, "m", buildings=[building])
    at = {b.area: b for b in boxes}
    return at["living"], at["garage"]


def test_a_detached_building_with_a_blank_place_is_where_it_always_was():
    elements = _elements(
        _room("living", width_m=10.0, depth_m=6.0),
        _room("garage", width_m=4.0, depth_m=3.0),
    )
    plain, _ = _place(elements, "m", buildings=[["garage"]])
    blank, _ = _place(
        elements,
        "m",
        buildings=[
            {"area_ids": ["garage"], "side": None, "gap_m": None, "along_m": None}
        ],
    )
    assert blank == plain
    at = {b.area: b for b in plain}
    assert at["garage"].x == pytest.approx(at["living"].x + 10.0 + 2.0)
    assert at["garage"].y == pytest.approx(at["living"].y)


@pytest.mark.parametrize(
    ("side", "gap", "x", "y"),
    [
        ("E", 5.0, 10.0 + 5.0, 0.0),
        ("W", 5.0, -5.0 - 4.0, 0.0),
        ("N", 5.0, 0.0, 6.0 + 5.0),
        ("S", 5.0, 0.0, -5.0 - 3.0),
        ("N", None, 0.0, 6.0 + 2.0),  # the gap is 2 m when not given
        ("W", 0.0, -4.0, 0.0),  # touching
    ],
)
def test_a_detached_building_sits_on_its_side_of_the_house(side, gap, x, y):
    house, garage = _house_and_garage(side=side, gap_m=gap)
    assert garage.x - house.x == pytest.approx(x)
    assert garage.y - house.y == pytest.approx(y)


@pytest.mark.parametrize(
    ("side", "x", "y"),
    [
        ("N", 3.0, 6.0 + 2.0),  # from the west end
        ("S", 3.0, -2.0 - 3.0),
        ("E", 10.0 + 2.0, 3.0),  # from the south end
        ("W", -2.0 - 4.0, 3.0),
    ],
)
def test_a_detached_building_can_sit_along_its_side(side, x, y):
    house, garage = _house_and_garage(side=side, along_m=3.0)
    assert garage.x - house.x == pytest.approx(x)
    assert garage.y - house.y == pytest.approx(y)


def test_a_detached_building_with_only_a_gap_stays_east_of_the_house():
    house, garage = _house_and_garage(gap_m=7.0)
    assert garage.x - house.x == pytest.approx(10.0 + 7.0)


def test_where_a_detached_building_sits_is_part_of_the_cached_layout():
    elements = _elements(
        _room("living", width_m=10.0, depth_m=6.0),
        _room("garage", width_m=4.0, depth_m=3.0),
    )
    first, _ = _place(elements, "m", buildings=[{"area_ids": ["garage"], "side": "N"}])
    second, _ = _place(elements, "m", buildings=[{"area_ids": ["garage"], "side": "S"}])
    assert {b.area: b.y for b in first}["garage"] > 0
    assert {b.area: b.y for b in second}["garage"] < 0


@pytest.mark.parametrize("view", [0, 1, 2, 3])
def test_floors_drawn_apart_go_up_the_page_whichever_way_the_view_turns(view):
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0),
        _room("upstairs", width_m=3.0, depth_m=3.0),
    )
    floors = {"ground": 0, "upstairs": 1}
    boxes, _ = _place(elements, "m", floors)
    shifts = _floor_shifts(boxes, _floor_index(elements, set(floors), floors), view)
    assert shifts["ground"] == (0.0, 0.0)
    dx, dy = shifts["upstairs"]
    here = next(b for b in boxes if b.area == "upstairs")
    before = project((here.x, here.y, here.z), view)
    after = project((here.x + dx, here.y + dy, here.z), view)
    assert after[0] == pytest.approx(before[0])  # straight up the page
    # clear of the floor below: its lowest corner is above the ground's ceiling
    ground = next(b for b in boxes if b.area == "ground")
    top = min(
        project((ground.x + x, ground.y + y, ground.z + ground.height), view)[1]
        for x in (0.0, 3.0)
        for y in (0.0, 3.0)
    )
    low = max(
        project((here.x + dx + x, here.y + dy + y, here.z), view)[1]
        for x in (0.0, 3.0)
        for y in (0.0, 3.0)
    )
    assert low < top


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


def test_only_draws_the_chosen_rooms_and_their_registers():
    """A floor or a building drawn alone: its rooms and registers, nothing else."""
    house = {**HOUSE, "plenum_x_m": 0.0, "plenum_y_m": 0.0, "plenum_z_m": 0.0}
    elements = _elements(
        _room("den", width_m=4.0, depth_m=2.0, x_m=0.0, y_m=0.0),
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=10.0, y_m=0.0),
        _register("reg", "den", at_x_m=2.0, at_y_m=1.0, at_z_m=0.1),
        house=house,
    )
    assert "Den" in house_svg(elements, house)
    svg = house_svg(elements, house, only={"kitchen"})
    assert "Den" not in svg
    assert "Kitchen" in svg
    # the den's register is not drawn, so it is not reported as missing either
    assert "its room is not drawn" not in svg
    assert "run " not in svg


def test_a_floor_drawn_alone_leaves_out_another_floor_at_its_level():
    # a garage floor at the same level as the ground floor
    elements = _elements(
        _room("den", width_m=4.0, depth_m=2.0, x_m=0.0, y_m=0.0),
        _room("garage", width_m=4.0, depth_m=3.0, x_m=10.0, y_m=0.0),
    )
    floors = {"den": 0, "garage": 0}
    ground = house_svg(elements, HOUSE, floors=floors, level=0, only={"den"})
    assert "Den" in ground
    assert "Garage" not in ground
    garage = house_svg(elements, HOUSE, floors=floors, level=0, only={"garage"})
    assert "Garage" in garage
    assert "Den" not in garage


def test_walls_on_one_face_follow_each_other_along_it():
    """Walls with no length split the face between them, and walls with lengths
    take theirs in turn; none is stacked in the corner."""
    room = _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0)

    def stretches(*walls):
        elements = _elements(room, *walls)
        found = [e for e in elements.values() if e.kind == WALL]
        return [(s, e) for _, s, e in _wall_stretches(found, 4.0)]

    # no length typed: the helper's default is off, as a wall built by the form has none
    untyped = {"length_m": None}
    assert stretches(
        _wall("a", "hall", "S", **untyped), _wall("b", "hall", "S", **untyped)
    ) == [(0.0, 2.0), (2.0, 4.0)]
    assert stretches(
        _wall("a", "hall", "S", length_m=1.5), _wall("b", "hall", "S", **untyped)
    ) == [(0.0, 1.5), (1.5, 4.0)]
    # lengths that overrun the face are scaled down to fit it, in turn
    assert stretches(
        _wall("a", "hall", "S", length_m=3.0), _wall("b", "hall", "S", length_m=3.0)
    ) == [(0.0, 2.0), (2.0, 4.0)]


def test_windows_in_one_wall_have_a_gap_between_them():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _wall("s", "hall", "S"),
        _window("w1", "s", width_m=0.8, height_m=1.1),
        _window("w2", "s", width_m=0.8, height_m=1.1),
    )
    box = _box(next(e for e in elements.values() if e.kind == ROOM), 0.0, 0.0, 0.0, "m")
    first, second = _openings(box, "S", [elements["w1"], elements["w2"]], [])
    assert second.points[0][0] - first.points[1][0] == pytest.approx(OPENING_GAP)


def test_a_window_goes_its_distance_from_the_left_end_seen_from_outside():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _wall("s", "hall", "S"),
        _wall("w", "hall", "W"),
        _window("s1", "s", width_m=0.8, height_m=1.1, from_left_m=0.5),
        _window("w1", "w", width_m=0.8, height_m=1.1, from_left_m=0.5),
        _window("w2", "w", width_m=0.6, height_m=1.1),
    )
    box = _box(next(e for e in elements.values() if e.kind == ROOM), 0.0, 0.0, 0.0, "m")
    # a south wall's left end, from outside, is its west end
    (south,) = _openings(box, "S", [elements["s1"]], [])
    assert (south.points[0][0], south.points[1][0]) == pytest.approx((0.5, 1.3))
    # a west wall's is its north end: 0.5 m back from y = 3
    placed, loose = _openings(box, "W", [elements["w1"], elements["w2"]], [])
    assert (placed.points[0][1], placed.points[1][1]) == pytest.approx((1.7, 2.5))
    # the window with no distance is centred on what is left of the wall
    assert (loose.points[0][1], loose.points[1][1]) == pytest.approx((0.55, 1.15))


def test_links_are_drawn_as_arrows_to_the_rooms_beside_above_and_below():
    elements = _elements(
        _room(
            "hall",
            width_m=4.0,
            depth_m=3.0,
            x_m=0.0,
            y_m=0.0,
            beside=["den"],
            above=["bed"],
        ),
        _room("den", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0),
        _room("bed", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
    )
    svg = room_svg(elements, HOUSE, "hall")
    assert 'data-layer="links"' in svg
    assert "Den" in svg
    assert "above: Bed" in svg
    # and from the room above, the one below is shown
    assert "below: Hall" in room_svg(elements, HOUSE, "bed")


def test_the_plan_draws_its_connections_and_the_rooms_names():
    elements = _elements(
        _room(
            "hall",
            width_m=4.0,
            depth_m=3.0,
            x_m=0.0,
            y_m=0.0,
            beside=["den"],
            open=["kitchen"],
        ),
        _room("den", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0),
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=3.0),
        _room("study", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=3.0),
    )
    svg = house_svg(elements, HOUSE)
    links = re.search(r'<g data-layer="connections">(.*?)</g>', svg).group(1)
    lines = re.findall(r"<polyline [^>]*/>", links)
    # hall-den and hall-kitchen; the study is linked to nothing
    assert len(lines) == 2
    # the open link is dashed, the other not
    assert sum("stroke-dasharray" in line for line in lines) == 1
    names = re.search(r'<g data-layer="names">(.*?)</g>', svg).group(1)
    for title in ("Hall", "Den", "Kitchen", "Study"):
        assert f">{title}</text>" in names
    # a floor drawn alone leaves out a link to a room not on it
    only = house_svg(elements, HOUSE, only={"hall", "den"})
    links = re.search(r'<g data-layer="connections">(.*?)</g>', only).group(1)
    assert len(re.findall(r"<polyline ", links)) == 1


def test_a_connection_runs_between_the_middles_of_the_rooms_floors():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, beside=["den"]),
        _room("den", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0),
    )
    scene = Scene()
    boxes, _ = _place(elements, "m")
    _add_connections(scene, boxes, elements)
    (line,) = [run for run in scene.lines if run.layer == "connections"]
    floors = sorted((b.x + b.width / 2, b.y + b.depth / 2, b.z) for b in boxes)
    assert sorted(line.points) == pytest.approx(floors)


def test_large_text_draws_the_labels_bigger():
    elements = _elements(_room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0))
    normal = room_svg(elements, HOUSE, "hall")
    large = room_svg(elements, HOUSE, "hall", large_text=True)
    assert 'font-size="11"' in normal
    assert f'font-size="{11 * LARGE_TEXT:g}"' in large


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
    # a row of 2 m and a gap, centred on the 4 m wall: the door first, then the window
    start = (4.0 - 2.0 - OPENING_GAP) / 2
    assert [x for x, _, _ in door.points] == pytest.approx(
        [start, start + 1.0, start + 1.0, start]
    )
    assert [z for _, _, z in door.points] == pytest.approx([0.0, 0.0, 2.0, 2.0])
    assert min(x for x, _, _ in glass.points) == pytest.approx(
        start + 1.0 + OPENING_GAP
    )
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


def test_an_inside_door_without_positions_is_placed_by_its_shared_wall():
    # neither room has a position: the hall is set against the kitchen's wall
    elements = _elements(*_two_rooms())
    svg = room_svg(elements, HOUSE, "kitchen")
    assert svg.count(DOOR_FILL) == 1
    assert "not drawn" not in svg
    elements = _elements(*_two_rooms(x_m=9.0, y_m=0.0))
    assert "do not touch" in room_svg(elements, HOUSE, "kitchen")


def test_rooms_with_no_position_are_chained_off_the_room_they_share_a_wall_with():
    # the kitchen is typed; the landing shares a wall with it, the bath with the landing
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4, x_m=0.0, y_m=0.0),
        _room("landing", width_m=2.0, depth_m=2.0),
        _room("bath", width_m=2.0, depth_m=2.0),
        Raw(
            "int",
            INTERNAL_WALL,
            "Wall to landing",
            {"area_id": "kitchen", "other_area_id": "landing"},
        ),
        Raw(
            "int2",
            INTERNAL_WALL,
            "Wall to bath",
            {"area_id": "landing", "other_area_id": "bath"},
        ),
    )
    boxes, notes = _place(elements, "m")
    where = {b.area: b for b in boxes}
    kitchen, landing, bath = where["kitchen"], where["landing"], where["bath"]
    assert _shared_face(kitchen, landing) is not None  # against the kitchen
    assert (kitchen.x, kitchen.y) == (0.0, 0.0)  # which stays where it was typed
    assert _shared_face(landing, bath) is not None
    assert any("no position typed" in note for note in notes)


def test_a_split_level_stays_on_its_floor():
    elements = _elements(
        _room("rec", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=-2.4),
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        # a split level's half flight up is still the main floor
        _room("den", width_m=3.0, depth_m=3.0, x_m=4.0, y_m=0.0, level_m=0.2),
        _room("landing", width_m=2.0, depth_m=2.0, x_m=7.0, y_m=0.0, level_m=1.0),
        _room("office", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
    )
    areas = {"rec", "kitchen", "den", "landing", "office"}
    assert _floor_index(elements, areas, None) == {
        "rec": 0,
        "kitchen": 1,
        "den": 1,
        "landing": 1,
        "office": 2,
    }


def test_more_than_three_and_a_half_feet_up_is_another_floor():
    elements = _elements(
        _room("main", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("half", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0, level_m=1.06),
        _room("loft", width_m=4.0, depth_m=3.0, x_m=8.0, y_m=0.0, level_m=1.08),
    )
    # 3 1/2 ft is 1.067 m: the half level stays, the loft starts a floor
    assert _floor_index(elements, {"main", "half", "loft"}, None) == {
        "main": 0,
        "half": 0,
        "loft": 1,
    }


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


def test_floors_from_the_house_draw_apart_even_with_no_heights_typed():
    # no level_m on the rooms: the floors come from the house's floors alone
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0),
        _room("upstairs", width_m=3.0, depth_m=3.0),
    )
    floors = {"ground": 0, "upstairs": 1}
    apart = house_svg(elements, HOUSE, exploded=True, floors=floors)
    together = house_svg(elements, HOUSE, floors=floors)
    assert "Floors drawn apart" in apart
    assert apart != together


def test_rooms_linked_beside_on_the_same_floor_are_drawn_together_without_a_wall():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _room("hall", width_m=2.0, depth_m=2.0, beside=["kitchen"]),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    assert _shared_face(where["kitchen"], where["hall"]) is not None


def _internal(id_: str, area: str, other: str, **data) -> Raw:
    return Raw(
        id_,
        INTERNAL_WALL,
        f"Wall to {other}",
        {"area_id": area, "other_area_id": other, **data},
    )


def test_linked_rooms_on_one_floor_pack_flush_around_a_hall():
    # rooms seeded on different outside-wall bands must still close every link
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0),
        _wall("ke", "kitchen", "E"),
        _wall("ks", "kitchen", "S"),
        _room("dining", width_m=3.0, depth_m=3.0),
        _wall("de", "dining", "E"),
        _wall("ds", "dining", "S"),
        _room("living", width_m=5.0, depth_m=4.0),
        _wall("le", "living", "E"),
        _wall("ln", "living", "N"),
        _room("office", width_m=3.0, depth_m=3.0),
        _wall("oe", "office", "E"),
        _wall("on", "office", "N"),
        _room("hall", width_m=2.0, depth_m=6.0),
        _room("bath", width_m=2.0, depth_m=2.0),
        _wall("bw", "bath", "W"),
        _room("laundry", width_m=2.0, depth_m=2.0),
        _wall("lw", "laundry", "W"),
        _internal("1", "hall", "kitchen"),
        _internal("2", "hall", "dining"),
        _internal("3", "hall", "living"),
        _internal("4", "hall", "office"),
        _internal("5", "hall", "bath"),
        _internal("6", "hall", "laundry"),
        _internal("7", "kitchen", "dining"),
        _internal("8", "living", "office"),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    # Hall is the hub: each room around it shares a face. Secondary links
    # (kitchen-dining, hall-office) can lose out once outside walls block a
    # seat; pin those with an internal wall's face when the layout needs them.
    for a, b in (
        ("hall", "kitchen"),
        ("hall", "dining"),
        ("hall", "living"),
        ("hall", "bath"),
        ("hall", "laundry"),
        ("living", "office"),
    ):
        assert _shared_face(where[a], where[b]) is not None, f"{a}-{b}"


def test_several_rooms_share_one_face_with_an_outside_stretch():
    # kitchen east in three sections: outside wall (window), open to the
    # landing, then a solid interior wall to the bath
    elements = _elements(
        _room("kitchen", width_m=4.5, depth_m=4.0, height_m=2.4, open=["landing"]),
        _wall("ke", "kitchen", "E", length_m=1.5),
        _wall("ks", "kitchen", "S", length_m=4.5),
        _wall("kn", "kitchen", "N", length_m=4.5),
        _wall("kw", "kitchen", "W", length_m=4.0),
        _window("kw_win", "ke", width_m=1.0, height_m=1.2),
        _room("landing", width_m=2.0, depth_m=1.5, height_m=2.4),
        _wall("le", "landing", "E", length_m=1.5),
        _wall("ls", "landing", "S", length_m=2.0),
        _internal("kl", "kitchen", "landing", open=True, face="E"),
        _room("bath", width_m=2.0, depth_m=2.0, height_m=2.4),
        _wall("be", "bath", "E", length_m=2.0),
        _internal("kb", "kitchen", "bath", face="E"),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    kitchen, landing, bath = where["kitchen"], where["landing"], where["bath"]
    to_landing = _shared_face(kitchen, landing)
    to_bath = _shared_face(kitchen, bath)
    assert to_landing is not None
    assert to_bath is not None
    assert to_landing[0] == to_bath[0] == "E"
    # the three stretches on that face must not overlap
    _, l0, l1 = to_landing
    _, b0, b1 = to_bath
    assert min(l1, b1) - max(l0, b0) <= 1e-6
    assert min(l1, 1.5) - max(l0, 0.0) <= 1e-6  # clear of the outside wall
    assert min(b1, 1.5) - max(b0, 0.0) <= 1e-6
    svg = room_svg(elements, HOUSE, "kitchen")
    assert (
        svg.count(WALL_FILL) + svg.count(INSIDE_FILL) >= 5
    )  # outside walls + solid wall to bath
    assert f'stroke-dasharray="{OPEN_DASH}"' in svg  # open to the landing
    assert "Dotted faces are open" in svg


def test_linked_component_is_seeded_without_a_band_gap():
    # two linked rooms on opposite outside edges: no 1 m gap left between them
    elements = _elements(
        _room("west", width_m=3.0, depth_m=3.0),
        _wall("ww", "west", "W"),
        _room("east", width_m=3.0, depth_m=3.0),
        _wall("ee", "east", "E"),
        _internal("we", "west", "east"),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    assert _shared_face(where["west"], where["east"]) is not None
    gap = where["east"].x - (where["west"].x + where["west"].width)
    assert gap == pytest.approx(0.0)


def test_a_link_between_floors_does_not_pull_the_rooms_side_by_side():
    # a room upstairs listed beside one downstairs stays on its own floor
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0),
        _room("ground2", width_m=3.0, depth_m=3.0, beside=["ground"]),
        _room("upstairs", width_m=3.0, depth_m=3.0, beside=["ground"]),
        _room("upstairs2", width_m=3.0, depth_m=3.0, beside=["upstairs"]),
    )
    floors = {"ground": 0, "ground2": 0, "upstairs": 1, "upstairs2": 1}
    boxes, _ = _place(elements, "m", floors)
    where = {b.area: b for b in boxes}
    assert where["upstairs"].z == where["upstairs2"].z > where["ground"].z
    assert _shared_face(where["ground"], where["ground2"]) is not None
    assert _shared_face(where["upstairs"], where["upstairs2"]) is not None
    # the upper floor is over the lower one, not beside it
    assert not _apart(
        replace(where["upstairs"], width=6.0, x=min(b.x for b in boxes if b.z > 0)),
        replace(where["ground"], width=6.0, x=min(b.x for b in boxes if b.z == 0)),
    )


def test_the_north_arrow_is_in_its_own_column_clear_of_the_rooms():
    elements = _elements(_room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0))
    svg = house_svg(elements, HOUSE)
    rooms = svg[: svg.index('data-layer="north"')]
    room_x = [
        float(point.split(",")[0])
        for points in re.findall(r'points="([^"]+)"', rooms)
        for point in points.split()
    ]
    north = svg[svg.index('data-layer="north"') :]
    north_x = [float(v) for v in re.findall(r'x[12]="([\d.]+)"', north)]
    assert max(room_x) < min(north_x)


def test_labels_are_not_cut_off_at_the_edge_of_the_drawing():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, beside=["den"]),
        _room("den", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0, beside=["hall"]),
    )
    svg = room_svg(elements, HOUSE, "hall")
    # the labels are centred on their point; the captions below the drawing are not
    labels = re.findall(
        r'<text x="([\d.]+)" y="[\d.-]+"[^>]*text-anchor="middle"[^>]*>(.*?)</text>',
        svg,
    )
    assert labels
    size = 11
    for x, inner in labels:
        text = re.sub(r"<[^>]+>", "", inner)
        half = 0.62 * size * len(text) / 2
        assert float(x) - half >= 0
        assert float(x) + half <= 900


@pytest.mark.parametrize(
    ("view", "near"),
    [(0, ("S", "W")), (1, ("N", "W")), (2, ("N", "E")), (3, ("S", "E"))],
)
def test_each_quarter_turn_looks_from_the_next_corner(view, near):
    assert near_faces(view) == near
    assert face_order(view)[2:] == near  # the near faces are drawn last
    # the corner looked from is the nearest point: lowest on the page
    corners = {"S": 0.0, "W": 0.0, "N": 10.0, "E": 10.0}
    seen = (
        corners["E"] if "E" in near else corners["W"],
        corners["N"] if "N" in near else corners["S"],
        0.0,
    )
    others = [
        (x, y, 0.0) for x in (0.0, 10.0) for y in (0.0, 10.0) if (x, y, 0.0) != seen
    ]
    assert all(project(seen, view)[1] > project(p, view)[1] for p in others)


def test_a_turned_drawing_says_where_it_looks_from():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _wall("s", "kitchen", "S"),
    )
    straight = house_svg(elements, HOUSE)
    turned = house_svg(elements, HOUSE, view=2)
    assert "Looking from the south-west." in straight
    assert "Looking from the north-east." in turned
    assert turned != straight
    assert house_svg(elements, HOUSE, view=4) == straight  # a full turn
    assert "Looking from the south-east." in room_svg(
        elements, HOUSE, "kitchen", view=3
    )


def test_overlays_have_anchors_for_rooms_walls_and_outlets():
    elements = _elements(
        _room(
            "rec",
            width_m=4.0,
            depth_m=3.0,
            x_m=0.0,
            y_m=0.0,
            level_m=-2.4,
            height_m=2.4,
        ),
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("living", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0, level_m=0.0),
        _wall("s", "kitchen", "S"),
        _register("reg", "living"),
    )
    for exploded in (False, True):
        svg = house_svg(elements, HOUSE, exploded=exploded)
        assert '<g data-layer="anchors" visibility="hidden">' in svg
        for area in ("rec", "kitchen", "living"):
            assert f'data-room="{area}"' in svg
        assert 'data-between="kitchen|living"' in svg  # side by side
        assert 'data-between="kitchen|rec"' in svg  # one over the other
        assert 'data-between="living|rec"' not in svg  # not over each other
        assert 'data-outside="kitchen|S"' in svg
        assert 'data-register="reg" data-room="living"' in svg
        assert '<g data-layer="rooms">' in svg
        assert '<g data-layer="notes">' in svg


def _roof(id_: str, areas: list[str], face: str, pitch: float = 30.0) -> Raw:
    return Raw(
        id_, "roof", f"{face} roof", {"area_ids": areas, "face": face, "pitch": pitch}
    )


def _roofs_layer(svg: str) -> str:
    return svg.split('<g data-layer="roofs">', 1)[1].split("</g>", 1)[0]


def test_a_gable_meets_at_the_ridge_and_has_its_two_ends():
    elements = _elements(
        _room("loft", width_m=6.0, depth_m=4.0, x_m=0.0, y_m=0.0, height_m=2.4),
        _roof("s", ["loft"], "S"),
        _roof("n", ["loft"], "N"),
    )
    layer = _roofs_layer(house_svg(elements, HOUSE))
    assert layer.count("<polygon") == 4  # two slopes, two gable ends
    assert layer.count(WALL_FILL) == 2


def test_one_roof_over_two_rooms_has_no_gable_between_them():
    elements = _elements(
        _room("office", width_m=4.0, depth_m=4.0, x_m=0.0, y_m=0.0),
        _room("master", width_m=6.0, depth_m=4.0, x_m=4.0, y_m=0.0),
        _roof("s", ["office", "master"], "S"),
        _roof("n", ["office", "master"], "N"),
    )
    layer = _roofs_layer(house_svg(elements, HOUSE))
    assert layer.count(WALL_FILL) == 2  # the two outer ends only


def test_a_lean_to_spans_its_room_and_no_roof_draws_no_layer():
    elements = _elements(
        _room("porch", width_m=3.0, depth_m=2.0, x_m=0.0, y_m=0.0),
        _roof("s", ["porch"], "S", pitch=15.0),
    )
    layer = _roofs_layer(house_svg(elements, HOUSE))
    assert layer.count("<polygon") == 1
    bare = _elements(_room("porch", width_m=3.0, depth_m=2.0, x_m=0.0, y_m=0.0))
    assert 'data-layer="roofs"' not in house_svg(bare, HOUSE)
    assert 'data-layer="roofs"' in room_svg(elements, HOUSE, "porch")


def test_a_roofs_r_value_is_in_its_own_layer_so_it_hides_with_the_roofs():
    elements = _elements(
        _room("porch", width_m=3.0, depth_m=2.0, x_m=0.0, y_m=0.0),
        _roof("s", ["porch"], "S", pitch=15.0),
    )
    svg = house_svg(elements, HOUSE, defaults={"roof_r": 5.0})
    roof_values = svg.split('<g data-layer="roofvalues">', 1)[1].split("</g>", 1)[0]
    assert "RSI 5.00" in roof_values


@pytest.mark.parametrize("view", [0, 1, 2, 3])
def test_the_far_gable_end_is_drawn_behind_the_roof(view):
    elements = _elements(
        _room("loft", width_m=6.0, depth_m=4.0, x_m=0.0, y_m=0.0),
        _roof("s", ["loft"], "S"),
        _roof("n", ["loft"], "N"),
    )
    layer = _roofs_layer(house_svg(elements, HOUSE, view=view))
    fills = [
        part.split('fill="', 1)[1].split('"', 1)[0]
        for part in layer.split("<polygon")[1:]
    ]
    roof = "#9c7b6b"  # ROOF_FILL
    wall = WALL_FILL.split('"')[1]
    # one gable end before both slopes (the far one), one after (the near one)
    assert fills == [wall, roof, roof, wall]


def test_a_short_outside_wall_is_drawn_its_length_and_the_rest_is_dashed():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("e", "kitchen", "E", length_m=1.5),
    )
    svg = room_svg(elements, HOUSE, "kitchen")
    assert svg.count(WALL_FILL) == 1
    # N, S and W have no wall; the east face's last 1.5 m has none either
    assert svg.count(DASHED) == 4


def test_walls_on_one_face_follow_each_other_and_the_gap_is_dashed():
    first = Element("a", WALL, "A", "kitchen", length_m=1.0)
    second = Element("b", WALL, "B", "kitchen", length_m=1.5)
    stretches = _wall_stretches([first, second], 3.0)
    assert [(w.id, s, e) for w, s, e in stretches] == [("a", 0.0, 1.0), ("b", 1.0, 2.5)]
    assert _gaps([(s, e) for _, s, e in stretches], 3.0) == [(2.5, 3.0)]


def test_sizes_and_r_values_are_labelled_on_their_own_layers():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S", r_value_si=3.5),
        _wall("e", "kitchen", "E"),  # no R-value typed
    )
    svg = room_svg(elements, HOUSE, "kitchen")
    assert 'data-layer="dims"' in svg and 'data-layer="rvalues"' in svg
    assert ">4 m wide<" in svg and ">3 m deep<" in svg and ">2.4 m high<" in svg
    assert ">4 m x 2.4 m<" in svg  # the south wall's length and height
    assert ">RSI 3.50<" in svg
    assert "R not typed" not in svg
    assert "Manual J" not in svg  # no default: blank, no footnote


def test_the_room_view_labels_its_doors_and_windows():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S"),
        _window("win", "s", width_m=1.0, height_m=1.2, glazing="double"),
        Raw("door", DOOR, "Front door", {"host": "s"}),  # size not typed
    )
    svg = room_svg(elements, HOUSE, "kitchen")
    assert ">window 1 m x 1.2 m, double glazed<" in svg
    assert ">door 0.813 m x 2.032 m<tspan" in svg  # footnoted a: size assumed
    assert "a: Size assumed" in svg
    assert "(size assumed)" not in svg
    # the house view does not label them
    assert ">window 1 m" not in house_svg(elements, HOUSE)


def test_an_outside_door_shows_its_r_value():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S"),
        Raw("door", DOOR, "Front door", {"host": "s", "r_value_si": 0.88}),
    )
    assert elements["door"].r_value_si == pytest.approx(0.88)
    assert ">RSI 0.88<" in room_svg(elements, HOUSE, "kitchen")


def test_an_untyped_part_shows_manual_js_default_footnoted_b():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S"),
    )
    svg = room_svg(
        elements,
        {"rotation": 0.0, "unit": FEET_INCHES},
        "kitchen",
        defaults={"wall_r": 3.52},
    )
    assert ">R-20<tspan" in svg and ">b</tspan>" in svg
    assert "b: Manual J default R-value" in svg
    assert "*" not in svg


def test_a_worked_out_room_size_is_footnoted_c_and_a_default_ceiling_a():
    # width typed, depth from the floor area, no ceiling height
    elements = _elements(_room("kitchen", width_m=4.0, floor_m2=12.0))
    svg = room_svg(elements, HOUSE, "kitchen")
    assert ">4 m wide</text>" in svg  # typed: no footnote
    assert ">3 m deep<tspan" in svg and ">c</tspan>" in svg
    assert ">2.4 m high<tspan" in svg and ">a</tspan>" in svg
    assert "c: Worked out" in svg and "a: Size assumed" in svg


def test_a_typed_room_size_has_no_footnote():
    elements = _elements(_room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4))
    svg = room_svg(elements, HOUSE, "kitchen")
    assert ">4 m wide</text>" in svg and ">3 m deep</text>" in svg
    assert ">2.4 m high</text>" in svg
    assert "c: Worked out" not in svg and "a: Size assumed" not in svg


def test_a_room_shaped_to_fit_has_both_sides_footnoted_c():
    elements = _elements(_room("kitchen", floor_m2=12.0, height_m=2.4))
    box = _place(elements, "m")[0][0]
    assert box.typed == frozenset({"height"})


def _positions(svg: str) -> str:
    found = re.search(r'<g data-layer="positions">(.*?)</g>', svg)
    return found.group(1) if found else ""


def test_rooms_with_a_typed_position_are_pinned_on_the_positions_layer():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _room("den", width_m=3.0, depth_m=3.0, x_m=4.0, y_m=1.5),
        _room("hall", width_m=2.0, depth_m=2.0),  # fitted: no pin
    )
    layer = _positions(house_svg(elements, HOUSE))
    assert ">4 m E, 1.5 m N<" in layer and ">0 m E, 0 m N<" in layer
    assert "Hall" not in layer
    assert "Origin" in layer  # the house's south-west corner
    assert layer.count("<circle") == 3  # the origin and the two pins
    # a room drawn alone has no positions layer
    assert 'data-layer="positions"' not in room_svg(elements, HOUSE, "den")


def test_a_position_west_or_south_of_the_origin_says_so():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _room("porch", width_m=2.0, depth_m=1.0, x_m=-2.0, y_m=-1.0),
    )
    assert ">2 m W, 1 m S<" in _positions(house_svg(elements, HOUSE))


def test_a_label_moves_to_the_nearest_clear_spot():
    box = (0.0, 40.0, 0.0, 10.0)
    below = (0.0, 40.0, 10.0, 20.0)  # touching the box's bottom, so clear
    blocked = (0.0, 40.0, -5.0, 15.0)  # overlaps the box, above and below
    assert _clear_shift(box, [], 10.0) == 0.0
    assert _clear_shift(box, [blocked], 10.0) == pytest.approx(20.0)  # the nearest
    everywhere = (0.0, 40.0, -1000.0, 1000.0)  # nothing clear: left where it is
    assert _clear_shift(box, [everywhere], 10.0) == 0.0
    assert _meet(box, below) is False


def test_r_values_are_in_the_house_unit():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4),
        _wall("s", "kitchen", "S", r_value_si=3.5),
    )
    svg = room_svg(elements, {"rotation": 0.0, "unit": FEET_INCHES}, "kitchen")
    assert ">R-20<" in svg  # 3.5 m2K/W is about R-20 ft2 F h/BTU


def test_an_internal_wall_is_drawn_from_both_rooms_even_without_a_door():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4, x_m=0.0, y_m=0.0),
        _room("landing", width_m=2.0, depth_m=3.0, height_m=2.4, x_m=4.0, y_m=0.0),
        Raw(
            "int",
            INTERNAL_WALL,
            "Wall to landing",
            {"area_id": "kitchen", "other_area_id": "landing"},
        ),
    )
    for area in ("kitchen", "landing"):
        svg = room_svg(elements, HOUSE, area)
        assert "not drawn" not in svg
        assert svg.count(INSIDE_FILL) == 1  # the shared wall
        assert svg.count(DASHED) == 3  # its other three faces


def test_an_open_internal_wall_is_dotted_not_solid():
    elements = _elements(
        _room("kitchen", width_m=4.0, depth_m=3.0, height_m=2.4, x_m=0.0, y_m=0.0),
        _room("landing", width_m=2.0, depth_m=3.0, height_m=2.4, x_m=4.0, y_m=0.0),
        Raw(
            "int",
            INTERNAL_WALL,
            "Opening to landing",
            {"area_id": "kitchen", "other_area_id": "landing", "open": True},
        ),
    )
    svg = room_svg(elements, HOUSE, "kitchen")
    assert WALL_FILL not in svg
    assert f'stroke-dasharray="{OPEN_DASH}"' in svg
    assert "Dotted faces are open" in svg


def test_an_implied_neighbour_is_dash_dotted():
    elements = _elements(
        _room("a", width_m=3.0, depth_m=3.0, height_m=2.4, x_m=0.0, y_m=0.0),
        _room(
            "b",
            width_m=3.0,
            depth_m=3.0,
            height_m=2.4,
            x_m=3.0,
            y_m=0.0,
            beside=["a"],
        ),
    )
    svg = room_svg(elements, HOUSE, "a")
    assert f'stroke-dasharray="{IMPLIED_DASH}"' in svg
    assert svg.count(DASHED) == 3  # the other three faces stay missing
    assert "Dash-dotted faces share a neighbour" in svg
    # the neighbour's face is not dashed, so the note leaves it out
    assert "Dashed faces have no wall part yet: N, S, W." in svg


def test_a_neighbour_is_not_seated_on_a_full_outside_wall():
    elements = _elements(
        _room("theater", width_m=4.0, depth_m=4.0),
        _wall("te", "theater", "E"),
        _wall("tn", "theater", "N"),
        _wall("tw", "theater", "W"),
        _room("laundry", width_m=3.0, depth_m=3.0, beside=["theater"]),
        _wall("ls", "laundry", "S"),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    shared = _shared_face(where["theater"], where["laundry"])
    assert shared is not None
    assert shared[0] != "E"  # theater's east face is a full outside wall


def test_an_internal_wall_face_pins_both_neighbours_to_that_side():
    # Kitchen is typed so neighbours seat against it. Its east face is partly
    # outside; face=E on both internal walls keeps landing and bath on that side
    # even though each neighbour's own north wall would otherwise pull them north.
    elements = _elements(
        _room("kitchen", width_m=4.5, depth_m=5.0, height_m=2.4, x_m=0.0, y_m=0.0),
        _wall("ke", "kitchen", "E", length_m=1.0),
        _wall("ks", "kitchen", "S", length_m=4.5),
        _wall("kw", "kitchen", "W", length_m=5.0),
        _room("landing", width_m=2.0, depth_m=1.5, height_m=2.4),
        _wall("ln", "landing", "N", length_m=2.0),
        _internal("kl", "kitchen", "landing", open=True, face="E"),
        _room("bath", width_m=2.0, depth_m=2.0, height_m=2.4),
        _wall("bn", "bath", "N", length_m=2.0),
        _internal("kb", "kitchen", "bath", face="E"),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    to_landing = _shared_face(where["kitchen"], where["landing"])
    to_bath = _shared_face(where["kitchen"], where["bath"])
    assert to_landing is not None and to_landing[0] == "E"
    assert to_bath is not None and to_bath[0] == "E"
    assert elements["kl"].face == "E"
    assert elements["kb"].face == "E"


def test_an_l_shaped_room_has_a_wing_against_the_face_it_names():
    elements = _elements(
        _room(
            "living",
            floor_m2=26.0,
            beside=["kitchen"],
            wing_width_m=2.0,
            wing_depth_m=3.0,
            wing_face="N",
        ),
        _room("kitchen", floor_m2=12.0),
    )
    boxes, notes = _place(elements, "m")
    living = next(b for b in boxes if b.area == "living")
    # the floor area is of the room and its wing together
    assert living.width * living.depth == pytest.approx(20.0, rel=0.01)
    dx, dy, width, depth = living.wing
    assert (width, depth) == pytest.approx((2.0, 3.0))
    assert dy == pytest.approx(living.depth, abs=0.02)  # on its north face
    assert -0.02 <= dx <= living.width - width + 0.02  # and within it
    assert any("L-shaped" in note for note in notes)
    assert not any("could not be placed" in note for note in notes)
    assert len(boxes) == 2  # the wing is part of its room


def test_a_placed_rooms_wing_is_at_the_south_end_of_its_face():
    elements = _elements(
        _room(
            "den",
            width_m=4.0,
            depth_m=3.0,
            x_m=1.0,
            y_m=2.0,
            wing_width_m=1.5,
            wing_depth_m=1.0,
            wing_face="E",
        ),
    )
    (den,), _ = _place(elements, "m")
    assert den.wing == pytest.approx((4.0, 0.0, 1.5, 1.0))
    svg = house_svg(elements, {"unit": "m"})
    assert svg.startswith("<svg")


def test_a_wing_with_only_a_floor_area_is_shaped_to_fit():
    elements = _elements(
        _room(
            "living",
            floor_m2=26.0,
            beside=["kitchen"],
            wing_floor_m2=6.0,
            wing_face="E",
        ),
        _room("kitchen", floor_m2=12.0),
    )
    boxes, notes = _place(elements, "m")
    living = next(b for b in boxes if b.area == "living")
    assert living.width * living.depth == pytest.approx(20.0, rel=0.01)
    dx, _, width, depth = living.wing
    assert width * depth == pytest.approx(6.0, rel=0.02)
    assert dx == pytest.approx(living.width, abs=0.02)  # on its east face
    assert not any("could not be placed" in note for note in notes)


def _winged_pair(den_y: float) -> dict:
    return _elements(
        _room(
            "living",
            width_m=6.0,
            depth_m=4.0,
            x_m=0.0,
            y_m=0.0,
            beside=["den"],
            wing_width_m=2.0,
            wing_depth_m=3.0,
            wing_face="N",
        ),
        _room("den", width_m=3.0, depth_m=2.0, x_m=2.0, y_m=den_y),
        _internal("wall", "living", "den"),
    )


def test_an_internal_wall_against_a_wing_is_drawn_on_the_wing():
    # the den is a metre clear of the living room, against its wing's east face
    elements = _winged_pair(5.0)
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    parts = _parts(elements)
    inside, notes = _inside_parts(elements, parts, "living", where)
    assert (inside, notes) == ([], [])  # not on the main rectangle; no complaint
    ((wall, face, start, end),) = _wing_parts(parts, "living", where)
    assert (wall.id, face) == ("wall", "E")
    assert (start, end) == pytest.approx((1.0, 3.0))  # along the wing's face
    # from the den, the same wall is on its own west face
    ((_, den_face, _, _),), den_notes = _inside_parts(elements, parts, "den", where)
    assert (den_face, den_notes) == ("W", [])
    assert "not drawn" not in house_svg(elements, {"unit": "m"})


def test_rooms_whose_wings_touch_are_touching():
    elements = _elements(
        _room(
            "a",
            width_m=4.0,
            depth_m=3.0,
            x_m=0.0,
            y_m=0.0,
            wing_width_m=2.0,
            wing_depth_m=1.0,
            wing_face="E",
        ),
        _room(
            "b",
            width_m=3.0,
            depth_m=3.0,
            x_m=8.0,
            y_m=0.0,
            wing_width_m=2.0,
            wing_depth_m=1.0,
            wing_face="W",
        ),
        _internal("wall", "a", "b"),
    )
    boxes, _ = _place(elements, "m")
    where = {b.area: b for b in boxes}
    assert _shared_face(where["a"], where["b"]) is None
    assert _touching(where["a"], where["b"])
    # the wall between them is on each room's wing
    parts = _parts(elements)
    ((_, face, start, end),) = _wing_parts(parts, "a", where)
    assert (face, start, end) == ("E", pytest.approx(0.0), pytest.approx(1.0))
    assert _inside_parts(elements, parts, "a", where) == ([], [])


def test_a_door_with_no_size_is_28_inches_inside_and_32_outside():
    elements = _elements(
        *_two_rooms(x_m=4.0, y_m=1.0),
        _wall("s", "kitchen", "S"),
        Raw("front", DOOR, "Front door", {"host": "s"}),
        Raw("sized", DOOR, "Sized door", {"host": "s", "width_m": 1.0}),
    )
    assert _door_size(elements["door"]) == pytest.approx((28 * 0.0254, 80 * 0.0254))
    assert _door_size(elements["front"]) == pytest.approx((32 * 0.0254, 80 * 0.0254))
    # a typed width is kept, the height still defaults
    assert _door_size(elements["sized"]) == pytest.approx((1.0, 80 * 0.0254))


def test_inside_walls_are_not_the_colour_of_outside_walls():
    elements = _elements(*_two_rooms(x_m=4.0, y_m=1.0), _wall("s", "kitchen", "S"))
    inside = INSIDE_FILL
    assert inside != WALL_FILL
    for svg in (room_svg(elements, HOUSE, "kitchen"), house_svg(elements, HOUSE)):
        assert WALL_FILL in svg  # the kitchen's south wall
        assert inside in svg  # the wall it shares with the hall


def test_a_room_alone_has_anchors_for_its_walls_and_neighbours():
    elements = _elements(
        _room(
            "rec",
            width_m=4.0,
            depth_m=3.0,
            x_m=0.0,
            y_m=0.0,
            level_m=-2.4,
            height_m=2.4,
        ),
        _room("kitchen", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("living", width_m=4.0, depth_m=3.0, x_m=4.0, y_m=0.0, level_m=0.0),
        _wall("s", "kitchen", "S"),
    )
    svg = room_svg(elements, HOUSE, "kitchen")
    assert '<g data-layer="anchors" visibility="hidden">' in svg
    for area in ("kitchen", "living", "rec"):  # the neighbours are placed too
        assert f'data-room="{area}"' in svg
    assert 'data-between="kitchen|living"' in svg  # beside
    assert 'data-between="kitchen|rec"' in svg  # below
    assert 'data-between="living|rec"' not in svg
    assert 'data-outside="kitchen|S"' in svg


def _stairs(area: str, to: str, **data) -> Raw:
    return _room(area, room_type="stairs", stairs_to=to, **data)


def test_stairs_to_another_floor_are_a_flight_below_and_an_opening_above():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("upstairs", width_m=5.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
        _stairs("stairs", "upstairs", width_m=1.0, depth_m=2.0, x_m=4.0, y_m=0.0),
    )
    floors = {"hall": 0, "stairs": 0, "upstairs": 1}
    boxes, _ = _place(elements, "m", floors)
    stairs = next(b for b in boxes if b.area == "stairs")
    assert stairs.floor_area == "stairs"  # the flight is on its own (lower) floor
    assert stairs.top_area == "upstairs"
    assert stairs.z == 0.0
    assert stairs.top_z - stairs.z == pytest.approx(
        stairs.height
    )  # flight to the floor above
    below = house_svg(elements, HOUSE, floors=floors, level=0)
    above = house_svg(elements, HOUSE, floors=floors, level=1)
    assert OPENING_FILL not in below  # the lower floor shows only the flight
    assert (
        OPENING_FILL in above
    )  # the upper floor shows the opening, and nothing else of it


def test_stairs_from_the_floor_above_are_a_flight_on_the_lower_floor():
    # the stairs sit on the upper floor, and go down to the hall
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("upstairs", width_m=5.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
        _stairs("upstairs_stairs", "hall", width_m=1.0, depth_m=2.0, x_m=4.0, y_m=0.0),
    )
    floors = {"hall": 0, "upstairs_stairs": 1, "upstairs": 1}
    boxes, _ = _place(elements, "m", floors)
    stairs = next(b for b in boxes if b.area == "upstairs_stairs")
    assert stairs.floor_area == "hall"  # the flight is on the hall's floor
    assert stairs.top_area == "upstairs_stairs"
    assert stairs.z == 0.0


def test_stacked_stairs_line_up_on_every_floor():
    # basement to main, and main to the upper floor, in the same place
    elements = _elements(
        _room("cellar", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=-2.7),
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("upstairs", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
        _stairs("down", "hall", width_m=1.0, depth_m=2.0, x_m=4.0, y_m=0.0),
        _stairs("up", "upstairs", width_m=1.0, depth_m=2.0, x_m=4.0, y_m=0.0),
    )
    floors = {"cellar": -1, "hall": 0, "upstairs": 1, "down": -1, "up": 0}
    boxes, _ = _place(elements, "m", floors)
    down = next(b for b in boxes if b.area == "down")
    up = next(b for b in boxes if b.area == "up")
    assert (down.x, down.y) == (up.x, up.y)
    assert down.top_area == "hall" and up.top_area == "upstairs"
    assert down.top_z == pytest.approx(
        up.z
    )  # the upper flight starts where the lower one comes up
    svg = house_svg(elements, HOUSE, floors=floors, level=0)
    assert OPENING_FILL in svg  # the basement flight's opening, on the hall floor
    assert svg.count(OPENING_FILL) == 1


def test_stairs_to_a_room_on_the_same_floor_are_an_ordinary_room():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _stairs("stairs", "hall", width_m=1.0, depth_m=2.0, x_m=4.0, y_m=0.0),
    )
    boxes, _ = _place(elements, "m", {"hall": 0, "stairs": 0})
    stairs = next(b for b in boxes if b.area == "stairs")
    assert stairs.top_area is None and stairs.top_z is None


def test_stairs_listed_as_above_others_stack_without_positions():
    elements = _elements(
        _room("cellar", width_m=4.0, depth_m=3.0, level_m=-2.7),
        _room("hall", width_m=4.0, depth_m=3.0, level_m=0.0),
        _room("upstairs", width_m=4.0, depth_m=3.0, level_m=2.7),
        _stairs("down", "hall", width_m=1.0, depth_m=2.0, above=["up"]),
        _stairs("up", "upstairs", width_m=1.0, depth_m=2.0),
    )
    floors = {"cellar": -1, "hall": 0, "upstairs": 1, "down": -1, "up": 0}
    boxes, _ = _place(elements, "m", floors)
    down = next(b for b in boxes if b.area == "down")
    up = next(b for b in boxes if b.area == "up")
    assert (down.x, down.y) == pytest.approx((up.x, up.y))  # one stack, not two stairs
    assert down.top_z == pytest.approx(up.z)


def test_stairs_get_temperature_anchors_on_each_floor_they_occupy():
    elements = _elements(
        _room("hall", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=0.0),
        _room("landing", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0, level_m=2.7),
        _stairs("stairs", "landing", width_m=1.0, depth_m=2.0, x_m=4.0, y_m=0.0),
    )
    floors = {"hall": 0, "landing": 1, "stairs": 0}
    below = house_svg(elements, HOUSE, floors=floors, level=0)
    above = house_svg(elements, HOUSE, floors=floors, level=1)
    assert 'data-between="hall|stairs"' in below  # its flight, on the hall's floor
    assert 'data-between="hall|stairs"' not in above
    assert 'data-between="landing|stairs"' in above  # its opening, on the landing's
    assert 'data-between="landing|stairs"' not in below
    assert 'data-room="stairs"' in above and 'data-room="stairs"' in below
