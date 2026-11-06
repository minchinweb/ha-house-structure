# Copyright (c) 2026 MinchinWeb
"""The isometric drawings: a room, the house from its rooms, and the heating runs."""

from __future__ import annotations

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
    FLOOR_GAP,
    LARGE_TEXT,
    OPENING_GAP,
    _box,
    _clear_shift,
    _footprint,
    _gaps,
    _meet,
    _north,
    _openings,
    _place,
    _shared_face,
    _wall_stretches,
    face_order,
    floor_lifts,
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


def test_rooms_without_a_position_go_after_the_placed_ones():
    elements = _elements(
        _room("placed", width_m=4.0, depth_m=3.0, x_m=0.0, y_m=0.0),
        _room("loose", width_m=2.0, depth_m=3.0),
    )
    boxes, notes = _place(elements, "m")
    loose = next(b for b in boxes if b.area == "loose")
    assert loose.x == pytest.approx(5.0)  # the placed room ends at 4 m, then a metre
    assert loose.y == pytest.approx(0.0)
    assert any("placed from its walls" in note for note in notes)


def test_loose_rooms_sit_against_the_edges_their_outside_walls_are_on():
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
    at = {b.area: (b.x, b.y) for b in boxes}
    # the east edge, with the north-east corner at the top and the room with only
    # an east wall between it and the south-east corner
    assert at["ne"][0] == at["e"][0] == at["se"][0] > at["w"][0]
    assert at["se"][1] < at["e"][1] < at["ne"][1]


def test_floor_groups_of_loose_rooms_are_spaced_apart():
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0),
        _room("upstairs", width_m=3.0, depth_m=3.0),
    )
    boxes, _ = _place(elements, "m", {"ground": 0, "upstairs": 1})
    at = {b.area: b for b in boxes}
    gap = at["upstairs"].y - (at["ground"].y + at["ground"].depth)
    assert gap == pytest.approx(FLOOR_GAP)


@pytest.mark.parametrize("view", [0, 1, 2, 3])
def test_upper_floor_groups_go_up_the_page_whichever_way_the_view_turns(view):
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0),
        _room("upstairs", width_m=3.0, depth_m=3.0),
    )
    boxes, _ = _place(elements, "m", {"ground": 0, "upstairs": 1}, view=view)
    screen = {
        b.area: project((b.x + b.width / 2, b.y + b.depth / 2, b.z), view)[1]
        for b in boxes
    }
    assert screen["upstairs"] < screen["ground"]


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
    assert (landing.x, landing.y) == pytest.approx((4.0, 0.0))  # kitchen's east face
    assert _shared_face(kitchen, landing) is not None
    assert _shared_face(landing, bath) is not None
    assert any("shared wall" in note for note in notes)


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


def test_floor_groups_keep_their_gap_and_do_not_snap_across_floors():
    # a room upstairs listed beside one downstairs must not pull the floors together
    elements = _elements(
        _room("ground", width_m=3.0, depth_m=3.0),
        _room("ground2", width_m=3.0, depth_m=3.0, beside=["ground"]),
        _room("upstairs", width_m=3.0, depth_m=3.0, beside=["ground"]),
        _room("upstairs2", width_m=3.0, depth_m=3.0, beside=["upstairs"]),
    )
    floors = {"ground": 0, "ground2": 0, "upstairs": 1, "upstairs2": 1}
    boxes, _ = _place(elements, "m", floors)
    where = {b.area: b for b in boxes}
    ground_top = max(where["ground"].y + 3.0, where["ground2"].y + 3.0)
    upstairs_bottom = min(where["upstairs"].y, where["upstairs2"].y)
    assert upstairs_bottom - ground_top >= FLOOR_GAP - 1e-6


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
        r'<text x="([\d.]+)" y="[\d.-]+"[^>]*text-anchor="middle"[^>]*>(.*?)</text>', svg
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
    assert ">door 0.9 m x 2.03 m<tspan" in svg  # footnoted a: size assumed
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
        assert svg.count(WALL_FILL) == 1  # the shared wall
        assert svg.count(DASHED) == 3  # its other three faces
