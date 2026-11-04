# Copyright (c) 2026 MinchinWeb
"""The furnace, air conditioner and building forms, and their summary."""

from __future__ import annotations

import pytest

from custom_components.house_structure.equipment import (
    BTU_H_TO_W,
    TON_TO_W,
    air_conditioner_from_form,
    air_conditioner_to_form,
    building_from_form,
    equipment_summary,
    furnace_from_form,
    furnace_to_form,
    parse_blower,
)
from custom_components.house_structure.geometry import FieldError
from custom_components.house_structure.model import Raw


def test_a_furnace_is_stored_in_si_and_shown_as_typed():
    form = {
        "area_id": "basement",
        "input_high_btuh": 80000,
        "input_low_btuh": 52000,
        "afue": 96,
        "blower_curve": "400 cfm = 0.30 inWC, 800 = 0.20, 1200 = 0.05",
    }
    data = furnace_from_form(form)
    assert data["input_high_w"] == pytest.approx(80000 * BTU_H_TO_W)
    assert data["input_low_w"] == pytest.approx(52000 * BTU_H_TO_W)
    assert data["afue"] == pytest.approx(0.96)
    assert len(data["blower"]) == 3
    assert furnace_to_form(data) == form


def test_a_one_stage_furnace_needs_only_its_input():
    data = furnace_from_form({"input_high_btuh": 60000})
    assert set(data) == {"area_id", "input_high_w"}
    assert data["area_id"] is None


@pytest.mark.parametrize(
    ("form", "field"),
    [
        ({}, "input_high_btuh"),
        ({"input_high_btuh": 0}, "input_high_btuh"),
        ({"input_high_btuh": 60000, "input_low_btuh": 70000}, "input_low_btuh"),
        ({"input_high_btuh": 60000, "afue": 150}, "afue"),
        ({"input_high_btuh": 60000, "blower_curve": "400 cfm"}, "blower_curve"),
    ],
)
def test_a_furnace_refuses_what_cannot_be(form, field):
    with pytest.raises(FieldError) as err:
        furnace_from_form(form)
    assert err.value.field == field


def test_the_blower_curve_carries_its_units():
    points = parse_blower("1000 l/s = 100 Pa, 500 = 200")
    assert points == [(0.5, 200.0), (1.0, 100.0)]
    with pytest.raises(FieldError):
        parse_blower("400 = 0.3, 400 = 0.2")


def test_an_air_conditioner_in_tons():
    form = {"area_id": "basement", "tons": 2.5, "sensible_btuh": 22000}
    data = air_conditioner_from_form(form)
    assert data["total_w"] == pytest.approx(2.5 * TON_TO_W)
    assert air_conditioner_to_form(data) == form
    with pytest.raises(FieldError) as err:
        air_conditioner_from_form({"tons": 1, "sensible_btuh": 13000})
    assert err.value.field == "sensible_btuh"


def test_a_building_needs_its_rooms():
    assert building_from_form({"area_ids": ["garage", ""]}) == {"area_ids": ["garage"]}
    with pytest.raises(FieldError):
        building_from_form({"area_ids": []})


def test_the_summary_lists_each_kind_in_order():
    raws = [
        Raw("w1", "wall", "South wall", {"area_id": "office"}),
        Raw("f1", "furnace", "Furnace", furnace_from_form({"input_high_btuh": 80000})),
        Raw("a1", "air_conditioner", "AC", air_conditioner_from_form({"tons": 2})),
        Raw("b1", "building", "Garage", {"area_ids": ["garage"]}),
    ]
    equipment, buildings = equipment_summary(raws)
    assert [f["id"] for f in equipment["furnaces"]] == ["f1"]
    assert equipment["furnaces"][0]["blower"] == []
    assert equipment["air_conditioners"][0]["total_w"] == pytest.approx(2 * TON_TO_W)
    assert buildings == [{"id": "b1", "title": "Garage", "area_ids": ["garage"]}]
    assert equipment_summary([]) == ({"furnaces": [], "air_conditioners": []}, [])
