# Copyright (c) 2026 MinchinWeb
"""The form and entity text: ``translations/en.json`` is ``strings.json``."""

from __future__ import annotations

import json
from pathlib import Path

PKG = Path(__file__).parent.parent / "custom_components" / "house_structure"


def _load(name: str) -> dict:
    return json.loads((PKG / name).read_text(encoding="utf-8"))


def test_english_matches_strings():
    # custom integrations only read translations/, which can't use [%key:...%]
    assert _load("translations/en.json") == _load("strings.json")
    assert "[%key:" not in (PKG / "strings.json").read_text(encoding="utf-8")


def test_every_part_has_its_forms():
    strings = _load("strings.json")
    for kind in (
        "room",
        "wall",
        "roof",
        "window",
        "door",
        "internal_wall",
        "register",
        "furnace",
        "air_conditioner",
        "building",
    ):
        steps = strings["config_subentries"][kind]["step"]
        assert set(steps) == {"user", "reconfigure"}


def test_every_entity_has_an_icon():
    names = _load("strings.json")["entity"]
    icons = _load("icons.json")["entity"]
    for platform, keys in names.items():
        assert set(keys) == set(icons[platform])


def test_the_drawing_fields_are_labelled():
    # the room, register and house forms take the positions and sizes the drawings use
    strings = _load("strings.json")
    steps = {
        "room": (("width", "depth", "x", "y", "level"),),
        "register": (("at_x", "at_y", "at_z"),),
    }
    for kind, (fields,) in steps.items():
        for step in ("user", "reconfigure"):
            form = strings["config_subentries"][kind]["step"][step]
            assert set(fields) <= set(form["data"]), (kind, step)
            assert set(fields) <= set(form["data_description"]), (kind, step)
    house = strings["config"]["step"]["user"]
    for key in ("plenum_x", "plenum_y", "plenum_z"):
        assert key in house["data"] and key in house["data_description"]
        assert f"invalid_{key}" in strings["config"]["error"]
