# Copyright (c) 2026 MinchinWeb
"""Set up a house through the config flow and check its devices and sensors."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.house_structure.constants import DOMAIN, UPDATED_EVENT
from custom_components.house_structure.sky import build_url

LAT, LON = 50.45, -104.6
NOW = datetime(2026, 11, 2, 19, 5, tzinfo=UTC)
SKY = {
    "minutely_15": {
        "time": ["2026-11-02T19:00", "2026-11-02T19:15"],
        "direct_normal_irradiance": [700.0, 690.0],
        "diffuse_radiation": [60.0, 60.0],
    }
}


async def _add(hass: HomeAssistant, entry_id: str, kind: str, form: dict) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry_id, kind), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM, result
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], form
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()


@pytest.fixture
async def house(hass: HomeAssistant, aioclient_mock, freezer):
    """A master bedroom with a south window, a west roof, a register and a bath."""
    freezer.move_to(NOW)
    hass.config.latitude, hass.config.longitude = LAT, LON
    aioclient_mock.get(build_url(LAT, LON), json=SKY)
    areas = ar.async_get(hass)
    master = areas.async_create("Master bedroom")
    bath = areas.async_create("Upstairs bath")
    entities = er.async_get(hass)
    for name, area in (("master_t", master), ("bath_t", bath)):
        entry = entities.async_get_or_create(
            "sensor",
            "demo",
            name,
            suggested_object_id=name,
            original_device_class="temperature",
        )
        entities.async_update_entity(entry.entity_id, area_id=area.id)
    hass.states.async_set("sensor.master_t", "21.5")
    hass.states.async_set("sensor.bath_t", "20.0")
    hass.states.async_set("cover.master_blinds", "open", {"current_position": 96})
    hass.states.async_set("climate.z3", "heat", {"hvac_action": "heating"})
    hass.states.async_set("fan.master_register", "off")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rotation": 10.4, "unit": "in"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry_id = result["result"].entry_id

    await _add(
        hass, entry_id, "room", {"area_id": master.id, "floor": 18000, "height": 96}
    )
    await _add(
        hass,
        entry_id,
        "wall",
        {"area_id": master.id, "face": "S", "length": 150, "height": 60},
    )
    await _add(
        hass, entry_id, "roof", {"area_id": master.id, "face": "W", "pitch": "12:12"}
    )
    entry = hass.config_entries.async_get_entry(entry_id)
    wall = next(s for s in entry.subentries.values() if s.subentry_type == "wall")
    await _add(
        hass,
        entry_id,
        "window",
        {
            "host": wall.subentry_id,
            "width": 48,
            "height": 55,
            "blind": "cover.master_blinds",
        },
    )
    await _add(
        hass,
        entry_id,
        "internal_wall",
        {"area_id": master.id, "other_area_id": bath.id},
    )
    await _add(
        hass,
        entry_id,
        "register",
        {"area_id": master.id, "climate": "climate.z3", "fan": "fan.master_register"},
    )
    return {"entry_id": entry_id, "master": master, "bath": bath, "wall": wall}


async def test_devices_are_in_the_room(hass: HomeAssistant, house) -> None:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), house["entry_id"])
    assert sorted(d.model for d in devices) == [
        "Heating register",
        "Internal wall",
        "Outside wall",
        "Roof",
        "Room",
        "Window",
    ]
    assert {d.area_id for d in devices} == {house["master"].id}


async def test_sensors(hass: HomeAssistant, house) -> None:
    wall = hass.states.get("sensor.master_bedroom_south_wall_sun")
    assert float(wall.state) == pytest.approx(661, abs=2)
    assert wall.attributes["azimuth"] == pytest.approx(190.4)
    assert wall.attributes["glass_m2"] == pytest.approx(1.703, abs=0.001)

    roof = hass.states.get("sensor.master_bedroom_west_roof_sun")
    assert roof.attributes["tilt"] == 45.0

    window = hass.states.get("sensor.master_bedroom_south_window_solar_gain")
    # 661 W/m2 on 1.703 m2, 0.7 through the glass, blind 96% open
    assert float(window.state) == pytest.approx(661 * 1.703 * 0.7 * 0.968, rel=0.01)
    room = hass.states.get("sensor.master_bedroom_room_solar_gain")
    assert float(room.state) == pytest.approx(float(window.state))
    assert room.attributes["volume_m3"] == pytest.approx(
        18000 * 96 * 0.0254**3, rel=1e-3
    )

    across = hass.states.get(
        "sensor.master_bedroom_wall_to_upstairs_bath_temperature_difference"
    )
    assert float(across.state) == pytest.approx(1.5)
    assert (
        hass.states.get("binary_sensor.master_bedroom_register_heating").state == "on"
    )


async def test_closing_the_blind_cuts_the_gain(hass: HomeAssistant, house) -> None:
    entity = "sensor.master_bedroom_south_window_solar_gain"
    open_gain = float(hass.states.get(entity).state)
    hass.states.async_set("cover.master_blinds", "closed", {"current_position": 0})
    await hass.async_block_till_done()
    assert float(hass.states.get(entity).state) == pytest.approx(
        open_gain / 0.968 * 0.2, rel=0.01
    )


async def test_rooms_are_published(hass: HomeAssistant, house) -> None:
    rooms = hass.data[DOMAIN]["rooms"]
    master = rooms[house["master"].id]
    assert master["temperature_entity"] == "sensor.master_t"
    assert master["registers"][0]["climate"] == "climate.z3"
    assert master["windows"][0]["blind"] == "cover.master_blinds"
    assert rooms[house["bath"].id]["internal_walls"][0]["other_area_id"] == (
        house["master"].id
    )


async def test_a_change_is_announced(hass: HomeAssistant, house) -> None:
    events = []
    hass.bus.async_listen(UPDATED_EVENT, events.append)
    # reloading with nothing changed says nothing
    await hass.config_entries.async_reload(house["entry_id"])
    await hass.async_block_till_done()
    assert events == []
    await _add(
        hass,
        house["entry_id"],
        "register",
        {"area_id": house["bath"].id, "climate": "climate.z3"},
    )
    assert len(events) == 1


async def test_forms_refuse_what_cannot_be(hass: HomeAssistant, house) -> None:
    entry_id = house["entry_id"]
    result = await hass.config_entries.subentries.async_init(
        (entry_id, "room"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"area_id": house["master"].id}
    )
    assert result["errors"] == {"area_id": "room_exists"}

    result = await hass.config_entries.subentries.async_init(
        (entry_id, "internal_wall"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"area_id": house["bath"].id, "other_area_id": house["bath"].id},
    )
    assert result["errors"] == {"other_area_id": "invalid_other_area_id"}

    result = await hass.config_entries.subentries.async_init(
        (entry_id, "roof"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"area_id": house["bath"].id, "face": "N", "pitch": "steep"}
    )
    assert result["errors"] == {"pitch": "invalid_pitch"}


async def test_a_window_needs_a_wall(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(build_url(hass.config.latitude, hass.config.longitude), json=SKY)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unit": "cm"}
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_init(
        (result["result"].entry_id, "window"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_hosts"


async def test_editing_shows_the_house_unit(hass: HomeAssistant, house) -> None:
    result = await hass.config_entries.subentries.async_init(
        (house["entry_id"], "wall"),
        context={
            "source": SOURCE_RECONFIGURE,
            "subentry_id": house["wall"].subentry_id,
        },
    )
    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested["length"] == pytest.approx(150)
    assert suggested["height"] == pytest.approx(60)
