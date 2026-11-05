# Copyright (c) 2026 MinchinWeb
"""Set up a house through the config flow and check its devices and sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr
import pytest

from custom_components.house_structure.constants import (
    DOMAIN,
    OUTLINE,
    UPDATED_EVENT,
)
from custom_components.house_structure.devices import (
    area_temperature,
    area_temperature_choices,
    part_device,
)
from custom_components.house_structure.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.house_structure.geometry import Plane
from custom_components.house_structure.map_view import OutlineMapView
from custom_components.house_structure.sky import build_url, split
from custom_components.house_structure.sun import sun_position

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
        hass, entry_id, "room", {"area_id": master.id, "floor": "18000", "height": "96"}
    )
    await _add(
        hass,
        entry_id,
        "wall",
        {"area_id": master.id, "face": "S", "length": "150", "height": "60"},
    )
    await _add(
        hass,
        entry_id,
        "roof",
        {"area_ids": [master.id], "face": "W", "pitch": "12:12"},
    )
    entry = hass.config_entries.async_get_entry(entry_id)
    wall = next(s for s in entry.subentries.values() if s.subentry_type == "wall")
    await _add(
        hass,
        entry_id,
        "window",
        {
            "host": wall.subentry_id,
            "width": "48",
            "height": "55",
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


async def test_a_part_finds_its_device(hass: HomeAssistant, house, monkeypatch) -> None:
    wall_id = house["wall"].subentry_id
    device = part_device(hass, house["entry_id"], wall_id)
    assert device is not None
    assert device.model == "Outside wall"

    # Home Assistant 2026.11 on: looked up within the entry, not across them
    asked = []

    def by_identifier(identifier, config_entry_id):
        asked.append((identifier, config_entry_id))
        return device

    monkeypatch.setattr(
        dr.async_get(hass),
        "async_get_device_by_identifier",
        by_identifier,
        raising=False,
    )
    assert part_device(hass, house["entry_id"], wall_id) is device
    assert asked == [((DOMAIN, wall_id), house["entry_id"])]


async def test_sensors(hass: HomeAssistant, house) -> None:
    wall = hass.states.get("sensor.master_bedroom_south_wall_solar_exposure")
    assert float(wall.state) == pytest.approx(657, abs=2)
    assert wall.attributes["azimuth"] == pytest.approx(190.4)
    assert wall.attributes["glass_m2"] == pytest.approx(1.703, abs=0.001)

    roof = hass.states.get("sensor.master_bedroom_west_roof_solar_exposure")
    assert roof.attributes["tilt"] == 45.0

    window = hass.states.get("sensor.master_bedroom_south_window_solar_gain")
    # 657 W/m2 on 1.703 m2, 0.7 through the glass, blind 96% open
    assert float(window.state) == pytest.approx(657 * 1.703 * 0.7 * 0.968, rel=0.01)
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


async def test_two_temperature_sensors_in_a_room(hass: HomeAssistant, house) -> None:
    master = house["master"].id
    entities = er.async_get(hass)
    entry = entities.async_get_or_create(
        "sensor",
        "demo",
        "master_t2",
        suggested_object_id="master_t2",
        original_device_class="temperature",
    )
    entities.async_update_entity(entry.entity_id, area_id=master)
    hass.states.async_set("sensor.master_t2", "21.0", {"device_class": "temperature"})
    # neither can be picked, so the room has none until one is chosen
    assert area_temperature(hass, master) is None
    assert area_temperature_choices(hass, master) == [
        "sensor.master_t",
        "sensor.master_t2",
    ]
    ar.async_get(hass).async_update(master, temperature_entity_id="sensor.master_t2")
    assert area_temperature(hass, master) == "sensor.master_t2"
    assert area_temperature_choices(hass, master) == []


async def test_rooms_are_published(hass: HomeAssistant, house) -> None:
    rooms = hass.data[DOMAIN]["rooms"]
    master = rooms[house["master"].id]
    assert master["temperature_entity"] == "sensor.master_t"
    assert master["temperature_choices"] == []
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


def _record(hass: HomeAssistant) -> list:
    """The house's entity states written from now on."""
    written = []

    def keep(event) -> None:
        new = event.data["new_state"]
        if new is not None and event.data["entity_id"].split(".")[1].startswith(
            ("master_bedroom_", "upstairs_bath_")
        ):
            written.append((event.data["entity_id"], new.state))

    hass.bus.async_listen("state_changed", keep)
    return written


async def test_editing_a_part_does_not_reload(hass: HomeAssistant, house) -> None:
    written = _record(hass)
    window_id = "sensor.master_bedroom_south_window_solar_gain"
    room_id = "sensor.master_bedroom_room_solar_gain"
    before = float(hass.states.get(window_id).state)
    entry = hass.config_entries.async_get_entry(house["entry_id"])
    window = next(s for s in entry.subentries.values() if s.subentry_type == "window")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "window"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": window.subentry_id},
    )
    # half as wide, and no blind
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"host": house["wall"].subentry_id, "width": "24", "height": "55"},
    )
    assert result["type"] is FlowResultType.ABORT, result
    await hass.async_block_till_done()

    assert not [w for w in written if w[1] == "unavailable"]
    after = float(hass.states.get(window_id).state)
    assert after == pytest.approx(before / 2 / 0.968, rel=0.01)
    assert float(hass.states.get(room_id).state) == pytest.approx(after)
    assert "blind" not in hass.states.get(window_id).attributes
    # it no longer follows the blind
    hass.states.async_set("cover.master_blinds", "closed", {"current_position": 0})
    await hass.async_block_till_done()
    assert float(hass.states.get(window_id).state) == pytest.approx(after)


async def test_adding_and_removing_a_part(hass: HomeAssistant, house) -> None:
    written = _record(hass)
    await _add(
        hass,
        house["entry_id"],
        "register",
        {"area_id": house["bath"].id, "climate": "climate.z3"},
    )
    added = "binary_sensor.upstairs_bath_register_heating"
    assert hass.states.get(added).state == "on"
    assert not [w for w in written if w[1] == "unavailable"]

    entry = hass.config_entries.async_get_entry(house["entry_id"])
    register = next(
        s
        for s in entry.subentries.values()
        if s.subentry_type == "register" and s.data["area_id"] == house["bath"].id
    )
    hass.config_entries.async_remove_subentry(entry, register.subentry_id)
    await hass.async_block_till_done()
    assert hass.states.get(added) is None
    assert er.async_get(hass).async_get(added) is None
    assert hass.states.get("binary_sensor.master_bedroom_register_heating").state == (
        "on"
    )


async def test_a_missed_fetch_keeps_the_sky(
    hass: HomeAssistant, house, aioclient_mock, freezer
) -> None:
    entry = hass.config_entries.async_get_entry(house["entry_id"])
    coordinator = entry.runtime_data.coordinator
    wall = "sensor.master_bedroom_south_wall_solar_exposure"
    before = hass.states.get(wall).state
    aioclient_mock.clear_requests()
    aioclient_mock.get(build_url(LAT, LON), exc=TimeoutError)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert hass.states.get(wall).state == before

    # once the last answer no longer covers the time, the sky is gone
    freezer.move_to(NOW + timedelta(minutes=30))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(wall).state == "unavailable"


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
        result["flow_id"],
        {"area_ids": [house["bath"].id], "face": "N", "pitch": "steep"},
    )
    assert result["errors"] == {"pitch": "invalid_pitch"}

    # a window's own room must be one its wall or roof covers
    result = await hass.config_entries.subentries.async_init(
        (entry_id, "window"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "host": house["wall"].subentry_id,
            "area_id": house["bath"].id,
            "width": "10",
            "height": "10",
        },
    )
    assert result["errors"] == {"area_id": "invalid_area_id"}


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
    assert suggested["length"] == "150 in"
    assert suggested["height"] == "60 in"


async def test_reconfiguring_the_house_reloads_it_once(
    hass: HomeAssistant, house, caplog
) -> None:
    entry = hass.config_entries.async_get_entry(house["entry_id"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rotation": 0, "unit": "in"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["rotation"] == 0
    wall = hass.states.get("sensor.master_bedroom_south_wall_solar_exposure")
    assert wall.attributes["azimuth"] == pytest.approx(180.0)
    assert "should use it for scheduling a reload" not in caplog.text


async def test_the_sky_from_a_radiation_sensor(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    freezer.move_to(NOW)
    hass.config.latitude, hass.config.longitude = LAT, LON
    hass.states.async_set(
        "sensor.station_radiation", "400", {"unit_of_measurement": "W/m²"}
    )
    areas = ar.async_get(hass)
    master = areas.async_create("Master bedroom")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # the sensor source needs its sensor
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unit": "cm", "sky_source": "sensor"}
    )
    assert result["errors"] == {"sky_sensor": "invalid_sky_sensor"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "unit": "cm",
            "sky_source": "sensor",
            "sky_sensor": "sensor.station_radiation",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    await _add(
        hass,
        result["result"].entry_id,
        "wall",
        {"area_id": master.id, "face": "S", "length": "300", "height": "240"},
    )

    azimuth, elevation = sun_position(NOW, LAT, LON)
    direct, diffuse = split(400.0, elevation, NOW)
    expected = Plane(180.0, 90.0).light(direct, diffuse, azimuth, elevation)
    wall = hass.states.get("sensor.master_bedroom_south_wall_solar_exposure")
    assert float(wall.state) == pytest.approx(expected, abs=1)
    assert float(wall.state) > 400
    # Open-Meteo is never asked
    assert aioclient_mock.call_count == 0


def _outline(turn: float, lat: float, lon: float) -> list[tuple[float, float]]:
    """A 12 m by 8 m house turned ``turn`` degrees clockwise from north."""
    c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
    per = 111_320.0
    points = []
    for x, y in [(-6, -4), (6, -4), (6, 4), (-6, 4), (-6, -4)]:
        east, north = x * c + y * s, -x * s + y * c
        points.append(
            (lat + north / per, lon + east / (per * math.cos(math.radians(lat))))
        )
    return points


async def test_the_rotation_is_measured_and_drawn(hass: HomeAssistant, osm) -> None:
    osm.return_value = [_outline(10.4, hass.config.latitude, hass.config.longitude)]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    schema = result["data_schema"].schema
    rotation = next(k for k in schema if k == "rotation")
    assert rotation.description["suggested_value"] == pytest.approx(10.4, abs=0.05)
    assert OutlineMapView.url in result["description_placeholders"]["map"]
    assert "rotation=10.4" in result["description_placeholders"]["map"]

    # redrawing for another value saves nothing
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rotation": 15, "unit": "cm", "preview": True}
    )
    assert result["type"] is FlowResultType.FORM
    assert "rotation=15.0" in result["description_placeholders"]["map"]
    assert not hass.config_entries.async_entries(DOMAIN)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"rotation": 15, "unit": "cm"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["rotation"] == 15.0
    assert "preview" not in result["data"]
    osm.assert_called_once()  # fetched once, then kept


async def test_no_map_without_openstreetmap(hass: HomeAssistant, osm) -> None:
    osm.side_effect = OSError("busy")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert "Could not reach" in result["description_placeholders"]["map"]
    assert result["type"] is FlowResultType.FORM


async def _new_house(hass: HomeAssistant, unit: str) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unit": unit}
    )
    await hass.async_block_till_done()
    return result["result"].entry_id


def _suggested(result) -> dict:
    return {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }


async def test_sizes_in_feet_and_inches(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(build_url(hass.config.latitude, hass.config.longitude), json=SKY)
    entry_id = await _new_house(hass, "ft_in")
    den = ar.async_get(hass).async_create("Den")
    await _add(
        hass,
        entry_id,
        "wall",
        {"area_id": den.id, "face": "S", "length": "12' 6\"", "height": "8'"},
    )
    await _add(
        hass, entry_id, "room", {"area_id": den.id, "floor": "150", "height": "8 0"}
    )
    entry = hass.config_entries.async_get_entry(entry_id)
    wall, room = (
        next(s for s in entry.subentries.values() if s.subentry_type == kind)
        for kind in ("wall", "room")
    )
    assert wall.data["length_m"] == pytest.approx(3.81)
    assert wall.data["height_m"] == pytest.approx(2.4384)
    assert room.data["floor_m2"] == pytest.approx(150 * 0.3048**2)

    result = await hass.config_entries.subentries.async_init(
        (entry_id, "wall"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": wall.subentry_id},
    )
    assert _suggested(result)["length"] == "12' 6\""
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"area_id": den.id, "face": "S", "length": "long"}
    )
    assert result["errors"] == {"length": "invalid_length"}


async def test_sizes_in_another_unit(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(build_url(hass.config.latitude, hass.config.longitude), json=SKY)
    entry_id = await _new_house(hass, "ft_in")
    den = ar.async_get(hass).async_create("Den")
    await _add(
        hass,
        entry_id,
        "room",
        {"area_id": den.id, "floor": "14 m²", "height": "2.4 m", "volume": "33 m3"},
    )
    entry = hass.config_entries.async_get_entry(entry_id)
    room = next(iter(entry.subentries.values()))
    assert room.data["floor_m2"] == pytest.approx(14)
    assert room.data["height_m"] == pytest.approx(2.4)
    assert room.data["volume_m3"] == pytest.approx(33)

    result = await hass.config_entries.subentries.async_init(
        (entry_id, "room"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": room.subentry_id},
    )
    shown = _suggested(result)
    assert shown["height"] == "7' 10.5\""
    assert shown["floor"] == "150.695 ft²"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"area_id": den.id, "floor": "14 m"}
    )
    assert result["errors"] == {"floor": "invalid_floor"}


async def test_a_roof_over_several_rooms(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(build_url(hass.config.latitude, hass.config.longitude), json=SKY)
    entry_id = await _new_house(hass, "cm")
    areas = ar.async_get(hass)
    attic, loft = areas.async_create("Attic"), areas.async_create("Loft")

    result = await hass.config_entries.subentries.async_init(
        (entry_id, "roof"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"area_ids": [], "face": "S", "pitch": "30"}
    )
    assert result["errors"] == {"area_ids": "invalid_area_ids"}
    await _add(
        hass,
        entry_id,
        "roof",
        {"area_ids": [attic.id, loft.id], "face": "S", "pitch": "30"},
    )
    entry = hass.config_entries.async_get_entry(entry_id)
    roof = next(s for s in entry.subentries.values() if s.subentry_type == "roof")
    await _add(
        hass,
        entry_id,
        "window",
        {"host": roof.subentry_id, "area_id": loft.id, "width": "50", "height": "90"},
    )
    await hass.async_block_till_done()

    # the roof's device is in the first room, so its sensor is named after it
    sun = hass.states.get("sensor.attic_south_roof_solar_exposure")
    assert sun.attributes["area_ids"] == [attic.id, loft.id]
    assert hass.states.get("sensor.loft_south_skylight_solar_gain") is not None
    rooms = hass.data[DOMAIN]["rooms"]
    assert [r["title"] for r in rooms[loft.id]["roofs"]] == ["South roof"]
    assert [r["title"] for r in rooms[attic.id]["roofs"]] == ["South roof"]
    assert len(rooms[loft.id]["windows"]) == 1
    assert rooms[attic.id]["windows"] == []

    result = await hass.config_entries.subentries.async_init(
        (entry_id, "roof"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": roof.subentry_id},
    )
    assert _suggested(result)["area_ids"] == [attic.id, loft.id]


async def test_diagnostics(hass: HomeAssistant, house) -> None:
    entry = hass.config_entries.async_get_entry(house["entry_id"])
    hass.data[OUTLINE] = {
        "points": _outline(10.4, hass.config.latitude, hass.config.longitude)
    }
    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["house"]["rotation"] == 10.4
    assert data["skipped"] == []
    wall = next(p for p in data["parts"] if p["kind"] == "wall")
    assert wall["settings"]["length_m"] == pytest.approx(3.81)
    assert wall["built"]["azimuth"] == pytest.approx(190.4)
    assert wall["area"] == wall["device_area"] == "Master bedroom"
    assert wall["entities"][0]["state"] not in (None, "unavailable")
    areas = {a["name"]: a["parts"] for a in data["areas"]}
    assert len(areas["Master bedroom"]) == 6
    assert areas["Upstairs bath"] == []
    assert data["sky"]["last_update_success"]
    assert data["sky"]["now"]["direct_normal"] > 0
    # the outline as walls only: nothing in it gives the house's position
    assert data["outline"]["rotation"] == pytest.approx(10.4, abs=0.05)
    assert len(data["outline"]["walls"]) == 4
    assert str(hass.config.latitude) not in str(data)


async def test_rooms_beside_and_above(hass: HomeAssistant, house) -> None:
    areas = ar.async_get(hass)
    floors = fr.async_get(hass)
    upstairs = floors.async_create("Upstairs", level=1)
    attic = floors.async_create("Attic", level=2)
    hall = areas.async_create("Hall")
    loft = areas.async_create("Loft")
    for area, floor in (
        (house["master"], upstairs),
        (house["bath"], upstairs),
        (hall, upstairs),
        (loft, attic),
    ):
        areas.async_update(area.id, floor_id=floor.floor_id)
    entry_id = house["entry_id"]
    for area in (house["bath"], hall):
        await _add(hass, entry_id, "room", {"area_id": area.id})
    entry = hass.config_entries.async_get_entry(entry_id)
    master = next(
        s
        for s in entry.subentries.values()
        if s.subentry_type == "room" and s.data["area_id"] == house["master"].id
    )

    async def edit(form: dict | None = None):
        result = await hass.config_entries.subentries.async_init(
            (entry_id, "room"),
            context={"source": SOURCE_RECONFIGURE, "subentry_id": master.subentry_id},
        )
        if form is None:
            return result
        return await hass.config_entries.subentries.async_configure(
            result["flow_id"], form
        )

    # first shown, the other rooms upstairs are ticked, less the bath, which
    # the internal wall links already
    shown = await edit()
    assert _suggested(shown)["beside"] == [hall.id]
    assert shown["description_placeholders"]["linked"] == "Upstairs bath"

    form = {"area_id": house["master"].id, "floor": "18000", "height": "96"}
    result = await edit({**form, "beside": [hall.id], "above": [hall.id]})
    assert result["errors"] == {"above": "invalid_above"}
    result = await edit({**form, "beside": [hall.id], "above": [loft.id]})
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    rooms = hass.data[DOMAIN]["rooms"]
    assert {
        (n["area_id"], n["position"]) for n in rooms[house["master"].id]["neighbours"]
    } == {(hall.id, "beside"), (loft.id, "above"), (house["bath"].id, "beside")}
    assert {(n["area_id"], n["position"]) for n in rooms[hall.id]["neighbours"]} == {
        (house["master"].id, "beside")
    }
    sensor = hass.states.get("sensor.master_bedroom_room_solar_gain")
    assert len(sensor.attributes["neighbours"]) == 3

    # the hall's form names the master bedroom as already linked
    hall_room = next(
        s
        for s in hass.config_entries.async_get_entry(entry_id).subentries.values()
        if s.subentry_type == "room" and s.data["area_id"] == hall.id
    )
    shown = await hass.config_entries.subentries.async_init(
        (entry_id, "room"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": hall_room.subentry_id},
    )
    assert shown["description_placeholders"]["linked"] == "Master bedroom"
    # the same-floor rooms are ticked, and so is the master bedroom: that link
    # is real, so unticking it here is what removes it
    assert _suggested(shown)["beside"] == sorted([house["master"].id, house["bath"].id])

    # unticking the master bedroom removes the link from both rooms
    result = await hass.config_entries.subentries.async_configure(
        shown["flow_id"], {"area_id": hall.id, "beside": [house["bath"].id]}
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()
    rooms = hass.data[DOMAIN]["rooms"]
    assert {n["area_id"] for n in rooms[house["master"].id]["neighbours"]} == {
        loft.id,
        house["bath"].id,
    }
    assert {(n["area_id"], n["position"]) for n in rooms[hall.id]["neighbours"]} == {
        (house["bath"].id, "beside")
    }


async def test_a_door_follows_its_contact(hass: HomeAssistant, house) -> None:
    entry_id = house["entry_id"]
    entry = hass.config_entries.async_get_entry(entry_id)
    inside = next(
        s for s in entry.subentries.values() if s.subentry_type == "internal_wall"
    )
    hass.states.async_set("binary_sensor.bath_contact", "off")
    await _add(
        hass,
        entry_id,
        "door",
        {"host": inside.subentry_id, "sensor": "binary_sensor.bath_contact"},
    )
    # a door with no contact gets no sensor, but is still published
    await _add(
        hass,
        entry_id,
        "door",
        {"host": house["wall"].subentry_id, "width": "36", "height": "80"},
    )

    door = "binary_sensor.master_bedroom_door_to_upstairs_bath_open"
    assert hass.states.get(door).state == "off"
    attributes = hass.states.get(door).attributes
    assert attributes["other_area_id"] == house["bath"].id
    assert attributes["temperature_entity"] == "sensor.master_t"
    assert attributes["other_temperature_entity"] == "sensor.bath_t"
    hass.states.async_set("binary_sensor.bath_contact", "on")
    await hass.async_block_till_done()
    assert hass.states.get(door).state == "on"
    assert hass.states.get("binary_sensor.master_bedroom_south_door_open") is None

    rooms = hass.data[DOMAIN]["rooms"]
    master, bath = rooms[house["master"].id], rooms[house["bath"].id]
    assert sorted(d["title"] for d in master["doors"]) == [
        "Door to Upstairs bath",
        "South door",
    ]
    assert [d["sensor"] for d in bath["doors"]] == ["binary_sensor.bath_contact"]
    assert master["walls"][0]["door_m2"] == pytest.approx(36 * 80 * 0.0254**2)


async def _paste(hass: HomeAssistant, entry_id: str, text: str):
    """Submit a sheet on the Reconfigure form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry_id}
    )
    # the form sends every field, so the house's unit and sky source go too
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sheet": text, "unit": "in", "sky_source": "open_meteo"}
    )


async def _paste_and_accept(hass: HomeAssistant, entry_id: str, text: str):
    """Paste a sheet, then accept the changes it lists."""
    result = await _paste(hass, entry_id, text)
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "sheet", result
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )


def _subentries(hass: HomeAssistant, entry_id: str, kind: str) -> list:
    entry = hass.config_entries.async_get_entry(entry_id)
    return [s for s in entry.subentries.values() if s.subentry_type == kind]


async def test_a_sheet_makes_the_walls_between_rooms(hass: HomeAssistant, house):
    """Rooms that share an edge get an internal wall, with its length, and a
    hallway's link is an opening."""
    areas = ar.async_get(hass)
    hall = areas.async_create("Hall")
    kitchen = areas.async_create("Kitchen")
    den = areas.async_create("Den")
    entry_id = house["entry_id"]
    text = (
        "kind,area_id,room_type,x,y,width,depth,level\n"
        "room,Hall,hallway,0,0,120,96,0\n"
        "room,Kitchen,room,120,0,96,96,0\n"
        "room,Den,room,120,96,96,48,0\n"
    )
    result = await _paste_and_accept(hass, entry_id, text)
    assert result["type"] is FlowResultType.ABORT, result
    assert result["reason"] == "sheet_imported"
    assert result["description_placeholders"]["added"] == "5"  # 3 rooms, 2 walls
    walls = {
        frozenset((s.data["area_id"], s.data["other_area_id"])): s
        for s in _subentries(hass, entry_id, "internal_wall")
    }
    hall_kitchen = walls[frozenset((hall.id, kitchen.id))]
    assert hall_kitchen.data["open"] is True  # the hallway opens onto it
    assert hall_kitchen.data["length_m"] == pytest.approx(96 * 0.0254)
    assert (
        hall_kitchen.title == "Opening to Kitchen"
        or hall_kitchen.title == "Opening to Hall"
    )
    kitchen_den = walls[frozenset((kitchen.id, den.id))]
    assert kitchen_den.data["open"] is False  # two rooms, no hallway or stairs
    assert kitchen_den.data["length_m"] == pytest.approx(96 * 0.0254)
    assert kitchen_den.title.startswith("Wall to")
    room_types = {
        s.data["area_id"]: s.data["room_type"]
        for s in _subentries(hass, entry_id, "room")
    }
    assert room_types[hall.id] == "hallway"
    assert room_types[kitchen.id] == "room"


async def test_the_sheet_round_trips(hass: HomeAssistant, house):
    """Exporting the house and pasting it back changes nothing, and adds nothing."""
    entry_id = house["entry_id"]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry_id}
    )
    text = result["description_placeholders"]["sheet"]
    assert "Master bedroom" in text
    assert "South wall" in text
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"sheet": text, "unit": "in", "sky_source": "open_meteo"},
    )
    assert result["step_id"] == "sheet", result
    assert result["description_placeholders"]["added"] == "0"
    assert result["description_placeholders"]["changed"] == "0", result[
        "description_placeholders"
    ]["changes"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )
    assert result["type"] is FlowResultType.ABORT, result


async def test_a_bad_row_saves_nothing(hass: HomeAssistant, house):
    entry_id = house["entry_id"]
    before = len(hass.config_entries.async_get_entry(entry_id).subentries)
    text = (
        "kind,area_id,host,width,height\n"
        "room,Nowhere,,120,96\n"
        "window,,Hallway wall,48,55\n"
    )
    result = await _paste(hass, entry_id, text)
    assert result["type"] is FlowResultType.FORM, result
    assert result["errors"] == {"sheet": "invalid_sheet"}
    problems = result["description_placeholders"]["problems"]
    assert "Row 1: no room called 'Nowhere'" in problems
    assert "Row 2: no part called 'Hallway wall'" in problems
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before


async def test_a_sheet_removes_a_link_from_both_rooms(hass: HomeAssistant, house):
    """A ``-`` before a room in a row's lists takes that link out of both rooms,
    even when the other room is not in the sheet, and keeps its internal wall."""
    areas = ar.async_get(hass)
    areas.async_create("Hall")
    kitchen = areas.async_create("Kitchen")
    den = areas.async_create("Den")
    entry_id = house["entry_id"]
    text = (
        "kind,area_id,room_type,x,y,width,depth,level\n"
        "room,Hall,hallway,0,0,120,96,0\n"
        "room,Kitchen,room,120,0,96,96,0\n"
        "room,Den,room,120,96,96,48,0\n"
    )
    assert (await _paste_and_accept(hass, entry_id, text))["type"] is (
        FlowResultType.ABORT
    )
    kitchen_sub = next(
        s
        for s in _subentries(hass, entry_id, "room")
        if s.data["area_id"] == kitchen.id
    )
    assert den.id in kitchen_sub.data["beside"]  # derived from the footprints

    text = f"id,kind,area_id,beside\n{kitchen_sub.subentry_id},room,Kitchen,-Den\n"
    result = await _paste(hass, entry_id, text)
    assert (
        "Change Den: beside: Kitchen → blank"
        in (result["description_placeholders"]["changes"])
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )
    assert result["type"] is FlowResultType.ABORT, result
    assert result["description_placeholders"]["changed"] == "2"  # Kitchen and Den
    assert "no longer linked" in result["description_placeholders"]["notes"]

    rooms = {s.data["area_id"]: s.data for s in _subentries(hass, entry_id, "room")}
    assert den.id not in rooms[kitchen.id]["beside"]
    assert kitchen.id not in rooms[den.id]["beside"]
    walls = _subentries(hass, entry_id, "internal_wall")
    assert any(
        {s.data["area_id"], s.data["other_area_id"]} == {kitchen.id, den.id}
        for s in walls
    )  # the wall part is kept


async def test_a_sheet_adds_windows_doors_and_registers(hass: HomeAssistant, house):
    """Windows, doors and registers come in from a sheet, each in its wall or room."""
    entry_id = house["entry_id"]
    text = (
        "kind,host,width,height,area_id,climate\n"
        "window,South wall,36,48,,\n"
        "door,South wall,,,,\n"
        "register,,,,Master bedroom,climate.bedroom\n"
    )
    result = await _paste_and_accept(hass, entry_id, text)
    assert result["type"] is FlowResultType.ABORT, result
    assert result["description_placeholders"]["added"] == "3"
    assert _subentries(hass, entry_id, "window")
    assert _subentries(hass, entry_id, "door")
    assert _subentries(hass, entry_id, "register")


async def test_the_changes_wait_for_acceptance(hass: HomeAssistant, house):
    """A pasted sheet lists its changes, and saves nothing until they are accepted."""
    areas = ar.async_get(hass)
    areas.async_create("Pantry")
    entry_id = house["entry_id"]
    before = len(hass.config_entries.async_get_entry(entry_id).subentries)
    text = "kind,area_id,room_type,width,depth\nroom,Pantry,room,60,48\n"
    result = await _paste(hass, entry_id, text)
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "sheet"
    placeholders = result["description_placeholders"]
    assert placeholders["added"] == "1"
    assert "Add a room: Pantry" in placeholders["changes"]
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )
    assert result["type"] is FlowResultType.ABORT, result
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before + 1


async def test_reject_and_try_again_keeps_the_sheet(hass: HomeAssistant, house):
    """Rejecting the changes saves nothing and goes back to the form with the sheet
    still pasted in it."""
    areas = ar.async_get(hass)
    areas.async_create("Pantry")
    entry_id = house["entry_id"]
    before = len(hass.config_entries.async_get_entry(entry_id).subentries)
    text = "kind,area_id,room_type,width,depth\nroom,Pantry,room,60,48\n"
    result = await _paste(hass, entry_id, text)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "try_again"}
    )
    assert result["type"] is FlowResultType.FORM, result
    assert result["step_id"] == "reconfigure"
    pasted = next(
        key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.schema == "sheet"
    )
    assert "Pantry" in pasted
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before


THREE_ROOMS = (
    "kind,area_id,room_type,x,y,width,depth,level\n"
    "room,Hall,hallway,0,0,120,96,0\n"
    "room,Kitchen,room,120,0,96,96,0\n"
    "room,Den,room,120,96,96,48,0\n"
)


async def test_a_partial_row_changes_only_its_cells(hass: HomeAssistant, house):
    """A row that fills in one cell changes that cell and nothing else: the room's
    footprint, its links and the other rooms are left as they are."""
    areas = ar.async_get(hass)
    areas.async_create("Hall")
    kitchen = areas.async_create("Kitchen")
    areas.async_create("Den")
    entry_id = house["entry_id"]
    assert (await _paste_and_accept(hass, entry_id, THREE_ROOMS))["type"] is (
        FlowResultType.ABORT
    )
    before = {s.data["area_id"]: s.data for s in _subentries(hass, entry_id, "room")}
    kitchen_sub = next(
        s
        for s in _subentries(hass, entry_id, "room")
        if s.data["area_id"] == kitchen.id
    )
    result = await _paste(
        hass, entry_id, f"id,kind,width\n{kitchen_sub.subentry_id},room,100\n"
    )
    assert result["step_id"] == "sheet", result
    changes = result["description_placeholders"]["changes"]
    assert changes.count("\n- ") == 1, changes
    assert "Change Kitchen: width:" in changes
    assert "depth" not in changes and "beside" not in changes
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )
    assert result["type"] is FlowResultType.ABORT, result
    after = {s.data["area_id"]: s.data for s in _subentries(hass, entry_id, "room")}
    assert len(after) == len(before)  # a missing row removes nothing
    assert after[kitchen.id]["beside"] == before[kitchen.id]["beside"]
    assert after[kitchen.id]["depth_m"] == before[kitchen.id]["depth_m"]
    assert after[kitchen.id]["width_m"] != before[kitchen.id]["width_m"]


async def test_a_removal_line_removes_an_unused_part(hass: HomeAssistant, house):
    """A line with only its kind and a name removes that part, once nothing uses it."""
    areas = ar.async_get(hass)
    areas.async_create("Pantry")
    entry_id = house["entry_id"]
    before = len(hass.config_entries.async_get_entry(entry_id).subentries)
    result = await _paste_and_accept(
        hass, entry_id, "kind,area_id,width,depth\nroom,Pantry,60,48\n"
    )
    assert result["type"] is FlowResultType.ABORT, result
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before + 1

    result = await _paste(hass, entry_id, "kind,name\nroom,Pantry\n")
    assert result["step_id"] == "sheet", result
    assert "Remove a room: Pantry" in result["description_placeholders"]["changes"]
    assert result["description_placeholders"]["removed"] == "1"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )
    assert result["type"] is FlowResultType.ABORT, result
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before


async def test_a_part_in_use_is_not_removed(hass: HomeAssistant, house):
    """A removal is refused while a part that stays uses the part: a room that has
    walls, and nothing is saved."""
    areas = ar.async_get(hass)
    for name in ("Hall", "Kitchen", "Den"):
        areas.async_create(name)
    entry_id = house["entry_id"]
    assert (await _paste_and_accept(hass, entry_id, THREE_ROOMS))["type"] is (
        FlowResultType.ABORT
    )
    before = len(hass.config_entries.async_get_entry(entry_id).subentries)
    result = await _paste(hass, entry_id, "kind,name\nroom,Den\n")
    assert result["errors"] == {"sheet": "invalid_sheet"}, result
    problems = result["description_placeholders"]["problems"]
    assert "Row 1: Den is used by" in problems
    assert len(hass.config_entries.async_get_entry(entry_id).subentries) == before


async def test_an_id_with_a_new_name_renames_the_part(hass: HomeAssistant, house):
    """A row with its id and only a new name renames that part; it is not removed."""
    areas = ar.async_get(hass)
    areas.async_create("Hall")
    kitchen = areas.async_create("Kitchen")
    areas.async_create("Den")
    entry_id = house["entry_id"]
    assert (await _paste_and_accept(hass, entry_id, THREE_ROOMS))["type"] is (
        FlowResultType.ABORT
    )
    kitchen_sub = next(
        s
        for s in _subentries(hass, entry_id, "room")
        if s.data["area_id"] == kitchen.id
    )
    count = len(hass.config_entries.async_get_entry(entry_id).subentries)
    result = await _paste(
        hass, entry_id, f"id,kind,name\n{kitchen_sub.subentry_id},room,Galley\n"
    )
    assert result["step_id"] == "sheet", result
    assert "Remove" not in result["description_placeholders"]["changes"]
    assert result["description_placeholders"]["removed"] == "0"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"action": "accept"}
    )
    assert result["type"] is FlowResultType.ABORT, result
    entry = hass.config_entries.async_get_entry(entry_id)
    assert len(entry.subentries) == count
    renamed = entry.subentries[kitchen_sub.subentry_id]
    assert renamed.title == "Galley"
    assert renamed.data["area_id"] == kitchen.id
    assert renamed.data["width_m"] == kitchen_sub.data["width_m"]


async def test_a_sheet_reads_feet_and_inch_marks(hass: HomeAssistant, house):
    """Sizes typed with their feet and inch marks, in a sheet, are saved in metres."""
    areas = ar.async_get(hass)
    pantry = areas.async_create("Pantry")
    entry_id = house["entry_id"]
    text = "kind,area_id,width,depth\nroom,Pantry,12' 6\",10' 0\"\n"
    result = await _paste_and_accept(hass, entry_id, text)
    assert result["type"] is FlowResultType.ABORT, result
    room = next(
        s for s in _subentries(hass, entry_id, "room") if s.data["area_id"] == pantry.id
    )
    assert room.data["width_m"] == pytest.approx(12.5 * 0.3048, rel=1e-3)
    assert room.data["depth_m"] == pytest.approx(10 * 0.3048, rel=1e-3)
