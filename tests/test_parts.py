# Copyright (c) 2026 MinchinWeb
"""Tests for the geometry, sky and model, which need no Home Assistant."""

from __future__ import annotations

from datetime import UTC, datetime
import math

import pytest

from custom_components.house_structure.constants import (
    DOOR,
    INTERNAL_WALL,
    REGISTER,
    ROOF,
    ROOM,
    WALL,
    WINDOW,
)
from custom_components.house_structure.geometry import (
    FieldError,
    Plane,
    blind_open_fraction,
    face_azimuth,
    format_feet_inches,
    format_size,
    parse_feet_inches,
    parse_pitch,
    parse_size,
    shaded,
    window_gain,
)
from custom_components.house_structure.model import (
    Raw,
    build,
    doors_in,
    neighbours,
    rooms_summary,
    windows_in,
)
from custom_components.house_structure.sky import at, build_url, parse, split
from custom_components.house_structure.sun import sun_position


@pytest.mark.parametrize(
    ("text", "degrees"),
    [("45", 45.0), ("12:12", 45.0), ("4/12", 18.43), (30, 30.0), ("30°", 30.0)],
)
def test_parse_pitch(text, degrees):
    assert parse_pitch(text) == pytest.approx(degrees, abs=0.01)


@pytest.mark.parametrize("text", ["steep", "95", "4:0"])
def test_parse_pitch_refuses(text):
    with pytest.raises(FieldError):
        parse_pitch(text)


def test_face_azimuth_turns_with_the_house():
    assert face_azimuth("S", 10.4) == pytest.approx(190.4)
    assert face_azimuth("N", -20) == pytest.approx(340.0)


def test_wall_facing_the_sun_gets_the_beam_and_half_the_sky():
    wall = Plane(azimuth=180.0, tilt=90.0)
    # sun due south at 30 degrees: cos(incidence) = cos(30)
    assert wall.light(800, 100, 180.0, 30.0) == pytest.approx(
        800 * 0.8660 + 50, abs=0.1
    )
    # sun behind the wall: only the sky
    assert wall.light(800, 100, 0.0, 30.0) == pytest.approx(50)
    # night
    assert wall.light(800, 100, 180.0, -5.0) == 0.0


def test_flat_roof_sees_the_whole_sky():
    roof = Plane(azimuth=180.0, tilt=0.0)
    assert roof.light(0, 100, 180.0, 30.0) == pytest.approx(100)


def test_shade_blocks_only_the_low_southern_beam():
    assert shaded(180.0, 5.0, 10.0)
    assert not shaded(180.0, 15.0, 10.0)
    assert not shaded(250.0, 5.0, 10.0)
    wall = Plane(azimuth=180.0, tilt=90.0, shade_below=10.0)
    assert wall.light(800, 100, 180.0, 5.0) == pytest.approx(50)


@pytest.mark.parametrize(
    ("state", "position", "fraction"),
    [
        ("open", 96, 0.96),
        ("closed", 0, 0.0),
        ("open", None, 1.0),
        ("closed", None, 0.0),
        ("unavailable", None, None),
    ],
)
def test_blind_open_fraction(state, position, fraction):
    assert blind_open_fraction(state, position) == fraction


def test_window_gain_with_the_blind():
    # 600 W/m2 on 1.7 m2 at 0.7: 714 W open
    assert window_gain(600, 1.7, 0.7) == pytest.approx(714)
    assert window_gain(600, 1.7, 0.7, 0.0, 0.2) == pytest.approx(142.8)
    assert window_gain(600, 1.7, 0.7, 0.5, 0.2) == pytest.approx(428.4)


def test_sun_at_regina_on_a_november_noon():
    # solar noon at Regina (104.6 W) on 2 November is about 18:45 UTC
    azimuth, elevation = sun_position(
        datetime(2026, 11, 2, 18, 45, tzinfo=UTC), 50.45, -104.6
    )
    assert azimuth == pytest.approx(180, abs=3)
    assert elevation == pytest.approx(24.8, abs=1.5)


WHEN = datetime(2026, 11, 2, 18, 45, tzinfo=UTC)


def test_split_gives_back_all_the_light():
    # a clear-ish noon: beam on the flat plus the sky is what the sensor read
    direct, diffuse = split(400.0, 25.0, WHEN)
    assert direct > diffuse > 0
    assert direct * math.sin(math.radians(25.0)) + diffuse == pytest.approx(400.0)


def test_split_overcast_is_nearly_all_sky():
    direct, diffuse = split(60.0, 25.0, WHEN)
    assert diffuse == pytest.approx(60.0, rel=0.05)
    assert direct < 15


def test_split_low_or_set_sun_is_all_sky():
    assert split(30.0, 1.0, WHEN) == (0.0, 30.0)
    assert split(-2.0, -10.0, WHEN) == (0.0, 0.0)


def test_split_caps_a_beam_brighter_than_can_be():
    # more light than the sun gives above the air, with the sun low
    direct, _ = split(500.0, 5.0, WHEN)
    assert direct <= 0.8 * 1361.0 * 1.034


BODY = {
    "minutely_15": {
        "time": ["2026-11-02T18:00", "2026-11-02T18:15", "2026-11-02T18:30"],
        "direct_normal_irradiance": [700.0, None, 650.0],
        "diffuse_radiation": [60.0, 55.0, 50.0],
    }
}


def test_sky_parse_skips_gaps_and_finds_the_quarter_hour():
    readings = parse(BODY)
    assert [r.direct_normal for r in readings] == [700.0, 650.0]
    # 18:20 falls in the 15 minutes ending 18:30
    found = at(readings, datetime(2026, 11, 2, 18, 20, tzinfo=UTC))
    assert found is not None
    assert found.direct_normal == 650.0
    assert at(readings, datetime(2026, 11, 2, 19, 0, tzinfo=UTC)) is None


def test_sky_url_asks_for_15_minute_light():
    url = build_url(50.45, -104.6)
    assert "minutely_15=direct_normal_irradiance%2Cdiffuse_radiation" in url


HOUSE = {"rotation": 10.4, "shade_below": 8.0}
RAWS = [
    Raw(
        "room", ROOM, "Master", {"area_id": "master", "floor_m2": 12.0, "height_m": 2.4}
    ),
    Raw(
        "wall",
        WALL,
        "Master south wall",
        {"area_id": "master", "face": "S", "length_m": 4.0, "height_m": 2.0},
    ),
    Raw(
        "roof",
        ROOF,
        "Master west roof",
        {"area_id": "master", "face": "W", "pitch": 45.0, "shade_below": 0.0},
    ),
    Raw(
        "win",
        WINDOW,
        "Master window",
        {
            "host": "wall",
            "width_m": 1.2192,
            "height_m": 1.397,
            "blind": "cover.master_bedroom_blinds",
        },
    ),
    Raw("lost", WINDOW, "Old window", {"host": "gone", "width_m": 1, "height_m": 1}),
    Raw(
        "int",
        INTERNAL_WALL,
        "Master to bath",
        {"area_id": "master", "other_area_id": "bath"},
    ),
    Raw(
        "reg",
        REGISTER,
        "Master register",
        {"area_id": "master", "climate": "climate.z3", "fan": "fan.master_register"},
    ),
    Raw("room2", ROOM, "Master again", {"area_id": "master"}),
]


def test_model_builds_the_master_bedroom():
    elements, problems = build(HOUSE, RAWS)
    assert set(elements) == {"room", "wall", "roof", "win", "int", "reg"}
    assert len(problems) == 2  # the window whose wall went, the second room

    room = elements["room"]
    assert room.volume_m3 == pytest.approx(28.8)

    wall = elements["wall"]
    assert wall.plane.azimuth == pytest.approx(190.4)
    assert wall.plane.shade_below == 8.0
    assert wall.glass_m2 == pytest.approx(1.703, abs=0.001)
    assert wall.net_m2 == pytest.approx(8.0 - 1.703, abs=0.001)

    roof = elements["roof"]
    assert (roof.plane.azimuth, roof.plane.tilt) == (pytest.approx(280.4), 45.0)
    assert roof.plane.shade_below == 0.0  # its own setting wins
    # no floor or length of its own, so it takes its room's floor, over the pitch
    assert roof.size_m2 == pytest.approx(room.floor_m2 / math.cos(math.radians(45)))

    window = elements["win"]
    assert window.area_id == "master"  # from its wall
    assert window.plane == wall.plane
    assert window.attributes()["blind"] == "cover.master_bedroom_blinds"

    assert elements["int"].attributes()["other_area_id"] == "bath"
    assert elements["reg"].attributes()["climate"] == "climate.z3"
    assert windows_in(elements, "master") == [window]


def test_facing_overrides_the_face():
    raws = [Raw("w", WALL, "Bay", {"area_id": "a", "face": "S", "facing": 135})]
    elements, _ = build(HOUSE, raws)
    assert elements["w"].plane.azimuth == 135.0


def test_rooms_summary_for_other_integrations():
    elements, _ = build(HOUSE, RAWS)
    rooms = rooms_summary(elements, {"master": "sensor.master_t"})
    master, bath = rooms["master"], rooms["bath"]
    assert master["title"] == "Master"
    assert master["volume_m3"] == pytest.approx(28.8)
    assert master["temperature_entity"] == "sensor.master_t"
    assert [w["in"] for w in master["windows"]] == ["wall"]
    assert master["windows"][0]["azimuth"] == pytest.approx(190.4)
    assert master["windows"][0]["blind"] == "cover.master_bedroom_blinds"
    assert master["walls"][0]["glass_m2"] == pytest.approx(1.703, abs=0.001)
    assert master["roofs"][0]["tilt"] == 45.0
    assert master["registers"] == [
        {
            "title": "Master register",
            "climate": "climate.z3",
            "fan": "fan.master_register",
            "free_area_in2": None,
            "flow_cfm": None,
            "duct": [],
            "upstream": None,
        }
    ]
    # the internal wall is in both rooms; the bath has no other parts
    assert master["internal_walls"][0]["other_area_id"] == "bath"
    assert bath["internal_walls"][0]["other_area_id"] == "master"
    assert bath["title"] is None and bath["windows"] == []


@pytest.mark.parametrize(
    ("text", "inches"),
    [
        ("12' 6\"", 150.0),
        ("12'-6 1/2\"", 150.5),
        ("12 ft 6 in", 150.0),
        ("12 6", 150.0),
        ("12.5'", 150.0),
        ("12", 144.0),
        ('150"', 150.0),
        ('1/2"', 0.5),
        ("12\u2019 6\u201d", 150.0),
        (12, 144.0),
    ],
)
def test_parse_feet_inches(text, inches):
    assert parse_feet_inches(text) == pytest.approx(inches * 0.0254)


@pytest.mark.parametrize("text", ["", "tall", "12' 6' 3", "-4'"])
def test_parse_feet_inches_refuses(text):
    with pytest.raises(ValueError):
        parse_feet_inches(text)


def test_format_feet_inches_round_trips():
    assert format_feet_inches(150.5 * 0.0254) == "12' 6.5\""
    assert format_feet_inches(143.99 * 0.0254) == "12' 0\""
    assert parse_feet_inches(format_feet_inches(3.81)) == pytest.approx(3.81, abs=0.003)


SHARED = [
    Raw(
        "roof",
        ROOF,
        "South roof",
        {"area_ids": ["attic", "loft"], "face": "S", "pitch": 30.0},
    ),
    Raw("sky", WINDOW, "Loft skylight", {"host": "roof", "area_id": "loft"}),
    Raw("sky2", WINDOW, "Skylight", {"host": "roof"}),
    Raw("sky3", WINDOW, "Stray skylight", {"host": "roof", "area_id": "kitchen"}),
]


def test_a_roof_over_several_rooms():
    elements, problems = build(HOUSE, SHARED)
    assert not problems
    roof = elements["roof"]
    assert roof.area_id == "attic"  # its device goes in the first room
    assert roof.area_ids == ("attic", "loft")
    assert roof.attributes()["area_ids"] == ["attic", "loft"]
    assert elements["sky"].area_id == "loft"
    assert elements["sky2"].area_id == "attic"  # none named: the first room
    assert elements["sky3"].area_id == "attic"  # not one of the roof's rooms
    rooms = rooms_summary(elements)
    assert [r["title"] for r in rooms["loft"]["roofs"]] == ["South roof"]
    assert rooms["attic"]["roofs"][0]["area_ids"] == ["attic", "loft"]
    assert [w["title"] for w in rooms["loft"]["windows"]] == ["Loft skylight"]


def test_a_roof_saved_with_one_room_still_has_it():
    elements, _ = build(HOUSE, RAWS)
    assert elements["roof"].area_ids == ("master",)


def test_neighbours_count_from_both_sides():
    raws = [
        Raw(
            "a",
            ROOM,
            "Kitchen",
            # itself and a repeat are dropped
            {"area_id": "kitchen", "beside": ["hall", "kitchen", "hall"]},
        ),
        Raw("b", ROOM, "Bedroom", {"area_id": "bed", "above": ["attic"]}),
        Raw("c", ROOM, "Hall", {"area_id": "hall", "above": ["bed"]}),
        Raw(
            "d",
            INTERNAL_WALL,
            "Wall to garage",
            {
                "area_id": "kitchen",
                "other_area_id": "garage",
                "length_m": 4.0,
                "height_m": 2.5,
            },
        ),
    ]
    elements, problems = build({}, raws)
    assert problems == []
    assert elements["a"].beside == ("hall",)
    links = neighbours(elements)
    assert links["kitchen"] == [
        {"area_id": "garage", "position": "beside", "area_m2": 10.0},
        {"area_id": "hall", "position": "beside", "area_m2": None},
    ]
    assert {(n["area_id"], n["position"]) for n in links["hall"]} == {
        ("kitchen", "beside"),
        ("bed", "above"),
    }
    assert {(n["area_id"], n["position"]) for n in links["bed"]} == {
        ("hall", "below"),
        ("attic", "above"),
    }
    rooms = rooms_summary(elements)
    assert rooms["bed"]["neighbours"] == links["bed"]
    # an area with no parts of its own is a neighbour, not a room
    assert "attic" not in rooms


@pytest.mark.parametrize(
    ("text", "unit", "power", "metres"),
    [
        ("3.2", "m", 1, 3.2),
        ("320", "cm", 1, 3.2),
        ("3.2 m", "ft_in", 1, 3.2),
        ("3.2m", "in", 1, 3.2),
        ("320 cm", "m", 1, 3.2),
        ("12' 6\"", "cm", 1, 3.81),
        ("12 ft 6 in", "m", 1, 3.81),
        ('150"', "mm", 1, 3.81),
        ("12 6", "ft_in", 1, 3.81),
        ("12", "ft_in", 1, 3.6576),
        ("2 Metres", "in", 1, 2.0),
        (2.5, "cm", 1, 0.025),
        ("14", "m", 2, 14.0),
        ("14 m²", "ft_in", 2, 14.0),
        ("14 m2", "in", 2, 14.0),
        ("100 sq ft", "m", 2, 100 * 0.3048**2),
        ("100 ft^2", "m", 2, 100 * 0.3048**2),
        ("100 square feet", "cm", 2, 100 * 0.3048**2),
        ("100", "ft_in", 2, 100 * 0.3048**2),
        ("40 m³", "ft", 3, 40.0),
        ("55 cm", "ft_in", 1, 0.55),
        ("550 mm", "ft_in", 1, 0.55),
        ("1400 ft3", "m", 3, 1400 * 0.3048**3),
        ("400 cu ft", "m", 3, 400 * 0.3048**3),
    ],
)
def test_parse_size(text, unit, power, metres):
    assert parse_size(text, unit, power) == pytest.approx(metres)


@pytest.mark.parametrize(
    ("text", "unit", "power"),
    [
        ("12 6", "m", 1),  # feet then inches only when the house is in them
        ("3 m", "m", 2),
        ("14 m²", "m", 1),
        ("12 ft 3", "m", 3),
        ("3,2 m", "m", 1),
        ("tall", "m", 1),
        ("3 furlongs", "m", 1),
        ("-3 m", "m", 1),
        ("", "m", 1),
    ],
)
def test_parse_size_refuses(text, unit, power):
    with pytest.raises(ValueError):
        parse_size(text, unit, power)


def test_format_size_reads_back():
    assert format_size(3.2, "m") == "3.2 m"
    assert format_size(3.81, "ft_in") == "12' 6\""
    assert format_size(14.0, "ft_in", 2) == "150.695 ft²"
    assert format_size(14.5, "mm", 2) == "14500000 mm²"
    for unit in ("m", "cm", "mm", "in", "ft", "ft_in"):
        for power in (1, 2, 3):
            shown = format_size(3.0, unit, power)
            assert parse_size(shown, unit, power) == pytest.approx(3.0, rel=1e-3)


def test_envelope_and_duct_fields_reach_the_summary():
    raws = [
        Raw(
            "room",
            ROOM,
            "Basement",
            {
                "area_id": "basement",
                "floor_m2": 40.0,
                "height_m": 2.3,
                "below_ground": True,
                "below_grade_m": 1.8,
            },
        ),
        Raw(
            "wall",
            WALL,
            "South wall",
            {
                "area_id": "basement",
                "face": "S",
                "length_m": 10.0,
                "height_m": 2.0,
                "r_value_si": 3.5,
            },
        ),
        Raw(
            "win",
            WINDOW,
            "Window",
            {
                "host": "wall",
                "width_m": 1.0,
                "height_m": 1.0,
                "glazing": "triple",
                "frame": "vinyl",
            },
        ),
        Raw(
            "reg",
            REGISTER,
            "Basement register",
            {
                "area_id": "basement",
                "climate": "climate.basement",
                "free_area_in2": 60.0,
                "flow_cfm": 90.0,
                "duct": [
                    {
                        "shape": "round",
                        "diameter_in": 4.0,
                        "length_ft": 14.0,
                        "fittings_k": 0.9,
                    }
                ],
            },
        ),
    ]
    elements, problems = build({"rotation": 0.0}, raws)
    assert problems == []
    rooms = rooms_summary(elements)
    room = rooms["basement"]
    assert room["below_grade_m"] == pytest.approx(1.8)
    assert room["walls"][0]["r_value_si"] == pytest.approx(3.5)
    assert room["windows"][0]["glazing"] == "triple"
    assert room["windows"][0]["frame"] == "vinyl"
    register = room["registers"][0]
    assert register["free_area_in2"] == pytest.approx(60.0)
    assert register["flow_cfm"] == pytest.approx(90.0)
    assert register["duct"][0]["diameter_in"] == pytest.approx(4.0)
    assert register["upstream"] is None
    assert room["below_grade_default"] is False
    wall = room["walls"][0]
    assert wall["face"] == "S"
    assert wall["length_m"] == pytest.approx(10.0)
    assert wall["height_m"] == pytest.approx(2.0)


def test_a_basement_without_its_own_depth_takes_the_houses():
    raws = [
        Raw("a", ROOM, "Basement", {"area_id": "basement", "below_ground": True}),
        Raw(
            "b",
            ROOM,
            "Rec room",
            {"area_id": "rec", "below_ground": True, "below_grade_m": 1.2},
        ),
        Raw("c", ROOM, "Kitchen", {"area_id": "kitchen"}),
    ]
    elements, _ = build({"below_grade_m": 1.8}, raws)
    rooms = rooms_summary(elements)
    assert rooms["basement"]["below_grade_m"] == pytest.approx(1.8)
    assert rooms["basement"]["below_grade_default"] is True
    assert rooms["rec"]["below_grade_m"] == pytest.approx(1.2)
    assert rooms["rec"]["below_grade_default"] is False
    # a room above ground takes no depth
    assert rooms["kitchen"]["below_grade_m"] is None
    assert rooms["kitchen"]["below_grade_default"] is False


def test_room_footprint_and_wall_face_reach_the_summary():
    raws = [
        Raw(
            "room",
            ROOM,
            "Den",
            {"area_id": "den", "width_m": 4.0, "depth_m": 3.0, "height_m": 2.4},
        ),
        # a wall with its own bearing takes the nearest face of the turned grid
        Raw("w", WALL, "Bay", {"area_id": "den", "face": "S", "facing": 100.0}),
    ]
    elements, _ = build({"rotation": 10.4}, raws)
    room = rooms_summary(elements)["den"]
    assert room["width_m"] == pytest.approx(4.0)
    assert room["depth_m"] == pytest.approx(3.0)
    assert room["walls"][0]["face"] == "E"
    assert room["walls"][0]["length_m"] is None


def test_missing_envelope_fields_are_none_not_errors():
    raws = [
        Raw("room", ROOM, "Office", {"area_id": "office"}),
        Raw(
            "wall",
            WALL,
            "Wall",
            {"area_id": "office", "face": "S", "length_m": 4.0, "height_m": 2.0},
        ),
    ]
    elements, _ = build({"rotation": 0.0}, raws)
    wall = rooms_summary(elements)["office"]["walls"][0]
    assert wall["r_value_si"] is None


DOORS = [
    *RAWS,
    Raw(
        "patio",
        DOOR,
        "South door",
        {
            "host": "wall",
            "width_m": 0.9,
            "height_m": 2.0,
            "sensor": "binary_sensor.patio",
        },
    ),
    Raw(
        "bathdoor",
        DOOR,
        "Door to bath",
        {"host": "int", "sensor": "binary_sensor.bath"},
    ),
    Raw("roofdoor", DOOR, "Hatch", {"host": "roof"}),
    Raw("gone", DOOR, "Old door", {"host": "nowhere"}),
]


def test_doors_take_their_rooms_from_their_wall():
    elements, problems = build(HOUSE, DOORS)
    assert len(problems) == 4  # as RAWS, plus the door in a roof and the lost one
    assert "roofdoor" not in elements and "gone" not in elements

    patio = elements["patio"]
    assert (patio.area_id, patio.other_area_id) == ("master", None)
    assert patio.plane == elements["wall"].plane
    assert patio.size_m2 == pytest.approx(1.8)
    assert patio.attributes()["sensor"] == "binary_sensor.patio"

    inside = elements["bathdoor"]
    assert (inside.area_id, inside.other_area_id) == ("master", "bath")
    assert inside.plane is None and inside.size_m2 is None

    # the wall's net area leaves out the door as well as the window
    wall = elements["wall"]
    assert wall.door_m2 == pytest.approx(1.8)
    assert wall.net_m2 == pytest.approx(8.0 - 1.703 - 1.8, abs=0.001)
    assert {d.id for d in doors_in(elements, "master")} == {"patio", "bathdoor"}
    assert [d.id for d in doors_in(elements, "bath")] == ["bathdoor"]


def test_doors_are_published_in_the_rooms_on_each_side():
    elements, _ = build(HOUSE, DOORS)
    rooms = rooms_summary(elements)
    master, bath = rooms["master"], rooms["bath"]
    by_title = {d["title"]: d for d in master["doors"]}
    assert by_title["South door"] == {
        "title": "South door",
        "in": "wall",
        "wall": "Master south wall",
        "other_area_id": None,
        "azimuth": pytest.approx(190.4),
        "width_m": 0.9,
        "height_m": 2.0,
        "area_m2": pytest.approx(1.8),
        "sensor": "binary_sensor.patio",
    }
    assert by_title["Door to bath"]["in"] == "internal_wall"
    assert by_title["Door to bath"]["other_area_id"] == "bath"
    assert [(d["title"], d["other_area_id"]) for d in bath["doors"]] == [
        ("Door to bath", "master")
    ]
    assert master["walls"][0]["door_m2"] == pytest.approx(1.8)
    assert master["internal_walls"][0]["door_m2"] == 0.0
