# Copyright (c) 2026 MinchinWeb
"""Tests for measuring and drawing the house rotation."""

from __future__ import annotations

import math

import pytest

from custom_components.house_structure.orientation import (
    choose_outline,
    outline_svg,
    ring_from_nominatim,
    wall_rotation,
)

HOME = (53.5, -113.5)
M = 111_320.0


def _box(rotation: float, centre=HOME, half=(6.0, 4.0)):
    """A closed rectangle turned ``rotation`` degrees clockwise from north."""
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    points = []
    for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)]:
        east = x * half[0] * c + y * half[1] * s
        north = -x * half[0] * s + y * half[1] * c
        points.append(
            (
                centre[0] + north / M,
                centre[1] + east / (M * math.cos(math.radians(centre[0]))),
            )
        )
    return points


@pytest.mark.parametrize("turn", [0.0, 10.4, -20.0, 44.0])
def test_wall_rotation_recovers_the_turn(turn):
    measured, squareness = wall_rotation(_box(turn))
    assert measured == pytest.approx(turn, abs=0.05)
    assert squareness == pytest.approx(1.0, abs=1e-3)


def test_wall_rotation_rejects_empty_outline():
    with pytest.raises(ValueError):
        wall_rotation([HOME])


def test_choose_outline_prefers_the_one_around_home():
    near = _box(5.0, (HOME[0] + 30 / M, HOME[1]))
    around = _box(12.0, HOME, half=(20.0, 20.0))
    assert choose_outline([near, around], HOME) is around
    assert choose_outline([near], HOME) is near
    assert choose_outline([], HOME) is None


def test_outline_svg_shows_polygon_and_rotated_arrow():
    svg = outline_svg(_box(10.4), 10.4)
    assert svg.startswith("<svg")
    assert "<polygon" in svg
    assert "rotation +10.4" in svg
    assert "south wall faces 190" in svg


def test_ring_from_nominatim_reads_a_building_polygon():
    body = {
        "category": "building",
        "geojson": {
            "type": "Polygon",
            "coordinates": [
                [[-113.5, 53.5], [-113.4, 53.5], [-113.4, 53.6], [-113.5, 53.5]]
            ],
        },
    }
    assert ring_from_nominatim(body)[0] == (53.5, -113.5)
    assert ring_from_nominatim({**body, "category": "highway"}) is None
    assert (
        ring_from_nominatim({"category": "building", "geojson": {"type": "Point"}})
        is None
    )
