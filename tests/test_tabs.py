# Copyright (c) 2026 MinchinWeb
"""The Thermal Lab page's tabs, the House tab's data, and what others need."""

from __future__ import annotations

from custom_components.house_structure.issues import missing, needed_by
from custom_components.house_structure.model import Element
from custom_components.house_structure.panel import house_view
from custom_components.house_structure.tabs import ordered


def test_tabs_are_sorted_by_order_then_title():
    registry = {
        "zones": {"title": "Zones", "url": "/lab/index.html", "order": 30},
        "house": {"title": "House", "url": "/hs/house.html", "order": 10},
        "hvac_design": {"title": "HVAC design", "url": "/mj/index.html", "order": 20},
        "extra": {"title": "Another", "url": "/x.html"},  # no order: last
    }
    assert [t["key"] for t in ordered(registry)] == [
        "house",
        "hvac_design",
        "zones",
        "extra",
    ]


def test_unusable_tabs_are_skipped():
    registry = {
        "Bad Key": {"title": "Bad", "url": "/a.html"},
        "no_title": {"url": "/a.html"},
        "elsewhere": {"title": "Elsewhere", "url": "https://example.com/"},
        "other_host": {"title": "Other host", "url": "//example.com/a.html"},
        "not_a_dict": "nope",
        "odd_order": {"title": "Odd order", "url": "/a.html", "order": "soon"},
    }
    assert [t["key"] for t in ordered(registry)] == ["odd_order"]
    assert ordered(None) == []


def test_the_house_tab_lists_rooms_by_floor():
    published = {
        "rooms": {"office": {}, "rec": {}, "kitchen": {}},
        "equipment": {"furnaces": [{"id": "f1"}], "air_conditioners": []},
        "buildings": [{"id": "b1", "title": "Garage", "area_ids": ["garage"]}],
    }
    names = {
        "office": "Office",
        "rec": "Rec room",
        "kitchen": "Kitchen",
        "garage": "Garage",
    }
    floors = {
        "rec": (-1, "Basement"),
        "office": (1, "Upstairs"),
        "kitchen": (0, "Main"),
    }
    view = house_view(published, names, floors)
    assert [r["name"] for r in view["rooms"]] == ["Rec room", "Kitchen", "Office"]
    assert view["rooms"][0] == {
        "area_id": "rec",
        "name": "Rec room",
        "floor": "Basement",
    }
    assert view["equipment"]["furnaces"] == [{"id": "f1"}]
    assert view["buildings"][0]["rooms"] == ["Garage"]
    assert house_view(None, {}, {})["equipment"] == {
        "furnaces": [],
        "air_conditioners": [],
    }


def _wall(part_id: str, size: float | None) -> Element:
    return Element(part_id, "wall", "South wall", "office", size_m2=size)


def test_a_missing_size_matters_only_when_something_needs_it():
    elements = {
        "w1": _wall("w1", None),
        "w2": _wall("w2", 12.0),
        "r1": Element("r1", "room", "Room", "office"),
    }
    assert missing(elements, needed_by({})) == {}

    registry = {
        "manual_j": {"title": "Manual J", "needs": ["wall_size", "room_floor"]},
        "home_thermal_lab": {"title": "Home Thermal Lab", "needs": ["wall_size"]},
        "junk": "not a dict",
        "odd": {"needs": ["nothing_we_know"]},
    }
    needs = needed_by(registry)
    assert needs == {
        "wall_size": ["Home Thermal Lab", "Manual J"],
        "room_floor": ["Manual J"],
    }
    assert missing(elements, needs) == {
        "w1": ("wall_size", "Home Thermal Lab and Manual J"),
        "r1": ("room_floor", "Manual J"),
    }
