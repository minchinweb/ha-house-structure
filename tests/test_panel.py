# Copyright (c) 2026 MinchinWeb
"""The Thermal Lab page, the equipment parts, and repairs raised on need."""

from __future__ import annotations

from homeassistant.components.frontend import DATA_PANELS
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import floor_registry as fr
from homeassistant.helpers import issue_registry as ir
import pytest

from custom_components.house_structure.constants import (
    DOMAIN,
    NEEDS,
    NEEDS_EVENT,
    TABS,
    TABS_EVENT,
    UPDATED_EVENT,
)
from custom_components.house_structure.equipment import BTU_H_TO_W
from custom_components.house_structure.panel import PANEL_PATH, STATIC_URL
from custom_components.house_structure.sky import build_url

LAT, LON = 53.5, -113.5
SKY = {
    "minutely_15": {
        "time": ["2026-11-02T19:00"],
        "direct_normal_irradiance": [0.0],
        "diffuse_radiation": [0.0],
    }
}


async def _add(hass: HomeAssistant, entry_id: str, kind: str, form: dict) -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry_id, kind), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM, result
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], form
    )
    await hass.async_block_till_done()
    return result


@pytest.fixture
async def house(hass: HomeAssistant, aioclient_mock):
    """A basement and an office (on two floors), and a wall with no size."""
    hass.config.latitude, hass.config.longitude = LAT, LON
    aioclient_mock.get(build_url(LAT, LON), json=SKY)
    floors = fr.async_get(hass)
    down = floors.async_create("Basement", level=-1)
    up = floors.async_create("Upstairs", level=1)
    areas = ar.async_get(hass)
    basement = areas.async_create("Basement", floor_id=down.floor_id)
    office = areas.async_create("Office", floor_id=up.floor_id)
    garage = areas.async_create("Garage")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rotation": 0, "unit": "m"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry_id = result["result"].entry_id
    await _add(hass, entry_id, "room", {"area_id": basement.id, "floor": "40"})
    await _add(hass, entry_id, "room", {"area_id": office.id})  # no floor area
    await _add(hass, entry_id, "wall", {"area_id": office.id, "face": "S"})
    return {
        "entry_id": entry_id,
        "basement": basement,
        "office": office,
        "garage": garage,
    }


async def test_the_page_is_in_the_sidebar(hass: HomeAssistant, house) -> None:
    panel = hass.data[DATA_PANELS][PANEL_PATH]
    assert panel.sidebar_title == "Thermal Lab"
    assert panel.config["url"].startswith(f"{STATIC_URL}/frame.html?v=")
    assert hass.data[TABS]["house"]["order"] == 10


async def test_tabs_are_sent_as_they_change(
    hass: HomeAssistant, house, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "house_structure/tabs"})
    assert (await client.receive_json())["success"]
    first = await client.receive_json()
    assert [t["key"] for t in first["event"]["tabs"]] == ["house"]

    hass.data[TABS]["hvac_design"] = {
        "title": "HVAC design",
        "url": "/manual_j_static/index.html",
        "order": 20,
    }
    hass.bus.async_fire(TABS_EVENT)
    second = await client.receive_json()
    assert [t["key"] for t in second["event"]["tabs"]] == ["house", "hvac_design"]


async def test_equipment_is_published_and_shown(
    hass: HomeAssistant, house, hass_ws_client
) -> None:
    entry_id = house["entry_id"]
    events = []
    hass.bus.async_listen(UPDATED_EVENT, events.append)
    result = await _add(
        hass,
        entry_id,
        "furnace",
        {
            "area_id": house["basement"].id,
            "input_high_btuh": 80000,
            "afue": 96,
            "blower_curve": "400 = 0.5, 1200 = 0.1",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await _add(hass, entry_id, "air_conditioner", {"tons": 2})
    await _add(hass, entry_id, "building", {"area_ids": [house["garage"].id]})
    assert len(events) == 3

    published = hass.data[DOMAIN]
    assert published["version"] == 1
    furnace = published["equipment"]["furnaces"][0]
    assert furnace["title"] == "Furnace"
    assert furnace["input_high_w"] == pytest.approx(80000 * BTU_H_TO_W)
    assert published["equipment"]["air_conditioners"][0]["title"] == "Air conditioner"
    assert published["buildings"][0]["area_ids"] == [house["garage"].id]

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
    by_model = {d.model: d for d in devices}
    assert by_model["Furnace"].area_id == house["basement"].id
    assert by_model["Detached building"].area_id == house["garage"].id

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "house_structure/house"})
    reply = await client.receive_json()
    assert reply["success"]
    view = reply["result"]
    assert [r["name"] for r in view["rooms"]] == ["Basement", "Office"]
    assert view["buildings"][0]["rooms"] == ["Garage"]
    assert view["equipment"]["furnaces"][0]["afue"] == pytest.approx(0.96)


async def test_a_furnace_form_refuses_a_bad_value(hass: HomeAssistant, house) -> None:
    result = await _add(
        hass, house["entry_id"], "furnace", {"input_high_btuh": 60000, "afue": 150}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"afue": "invalid_afue"}


async def test_a_furnace_can_be_changed(hass: HomeAssistant, house) -> None:
    entry_id = house["entry_id"]
    await _add(hass, entry_id, "furnace", {"input_high_btuh": 60000, "name": "Old"})
    entry = hass.config_entries.async_get_entry(entry_id)
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "furnace")
    result = await hass.config_entries.subentries.async_init(
        (entry_id, "furnace"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"input_high_btuh": 70000, "name": "New"}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    furnace = hass.data[DOMAIN]["equipment"]["furnaces"][0]
    assert furnace["title"] == "New"
    assert furnace["input_high_w"] == pytest.approx(70000 * BTU_H_TO_W)


async def test_repairs_wait_until_something_needs_the_size(
    hass: HomeAssistant, house
) -> None:
    def ours() -> dict:
        return {
            issue_id: issue
            for (domain, issue_id), issue in ir.async_get(hass).issues.items()
            if domain == DOMAIN
        }

    # the wall has no size and the office no floor, but nothing needs them yet
    assert ours() == {}

    hass.data.setdefault(NEEDS, {})["manual_j"] = {
        "title": "Manual J",
        "needs": ["wall_size", "room_floor"],
    }
    hass.bus.async_fire(NEEDS_EVENT)
    await hass.async_block_till_done()
    issues = ours()
    assert sorted(i.translation_key for i in issues.values()) == [
        "missing_floor",
        "missing_wall_size",
    ]
    assert {i.translation_placeholders["needed_by"] for i in issues.values()} == {
        "Manual J"
    }

    hass.data[NEEDS]["manual_j"]["needs"] = ["room_floor"]
    hass.bus.async_fire(NEEDS_EVENT)
    await hass.async_block_till_done()
    assert [i.translation_key for i in ours().values()] == ["missing_floor"]

    del hass.data[NEEDS]["manual_j"]
    hass.bus.async_fire(NEEDS_EVENT)
    await hass.async_block_till_done()
    assert ours() == {}
