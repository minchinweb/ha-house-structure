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
import pytest

from custom_components.house_structure.constants import (
    DOMAIN,
    OUTLINE,
    UPDATED_EVENT,
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
        hass, entry_id, "room", {"area_id": master.id, "floor": 18000, "height": 96}
    )
    await _add(
        hass,
        entry_id,
        "wall",
        {"area_id": master.id, "face": "S", "length": 150, "height": 60},
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
    assert float(wall.state) == pytest.approx(657, abs=2)
    assert wall.attributes["azimuth"] == pytest.approx(190.4)
    assert wall.attributes["glass_m2"] == pytest.approx(1.703, abs=0.001)

    roof = hass.states.get("sensor.master_bedroom_west_roof_sun")
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
        {"host": house["wall"].subentry_id, "width": 24, "height": 55},
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
    wall = "sensor.master_bedroom_south_wall_sun"
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
            "width": 10,
            "height": 10,
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
    assert suggested["length"] == pytest.approx(150)
    assert suggested["height"] == pytest.approx(60)


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
    wall = hass.states.get("sensor.master_bedroom_south_wall_sun")
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
        {"area_id": master.id, "face": "S", "length": 300, "height": 240},
    )

    azimuth, elevation = sun_position(NOW, LAT, LON)
    direct, diffuse = split(400.0, elevation, NOW)
    expected = Plane(180.0, 90.0).light(direct, diffuse, azimuth, elevation)
    wall = hass.states.get("sensor.master_bedroom_south_wall_sun")
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
        hass, entry_id, "room", {"area_id": den.id, "floor": 150, "height": "8 0"}
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
        {"host": roof.subentry_id, "area_id": loft.id, "width": 50, "height": 90},
    )
    await hass.async_block_till_done()

    # the roof's device is in the first room, so its sensor is named after it
    sun = hass.states.get("sensor.attic_south_roof_sun")
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
