# Copyright (c) 2026 MinchinWeb
"""Tests for the geometry, sky and model, which need no Home Assistant."""

from __future__ import annotations

from datetime import UTC, datetime
import math

import pytest

from custom_components.house_structure.constants import (
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
    parse_pitch,
    shaded,
    window_gain,
)
from custom_components.house_structure.model import (
    Raw,
    build,
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
    assert roof.size_m2 is None

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
        }
    ]
    # the internal wall is in both rooms; the bath has no other parts
    assert master["internal_walls"][0]["other_area_id"] == "bath"
    assert bath["internal_walls"][0]["other_area_id"] == "master"
    assert bath["title"] is None and bath["windows"] == []
