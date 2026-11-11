# Copyright (c) 2026 MinchinWeb
"""Sensors on each part of the house (see ``devices.py`` for the devices).

* Wall and roof: ``solar_exposure``, the sun and sky light on it (W/m2).
* Window: ``solar_gain``, the sun's heat through the glass (W), less what the
  blind keeps out.
* Room: ``solar_gain``, the sun's heat through all its windows (W); its
  attributes give the floor area, ceiling height and volume.
* Internal wall: ``temperature_difference``, this room minus the other.

Each sensor's attributes give the part's geometry (azimuth, tilt, area in m2,
host, rooms), so other integrations can use it without asking again.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfIrradiance,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import (
    DOMAIN,
    INTERNAL_WALL,
    OUTLINE,
    OUTLINE_SIGNAL,
    ROOF,
    ROOM,
    WALL,
    WINDOW,
)
from .coordinator import SkyCoordinator
from .devices import HouseData, area_temperature
from .entity import PartEntity, setup_parts
from .geometry import blind_open_fraction, window_gain
from .model import Element, neighbours, windows_in
from .sun import sun_position

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create each part's sensors on its device, now and as parts are added."""
    setup_parts(hass, entry, async_add_entities, _sensor_for)
    async_add_entities([OutlineSensor(entry)])


def _sensor_for(data: HouseData, element: Element) -> PartEntity | None:
    coordinator = data.coordinator
    if element.kind in (WALL, ROOF):
        return SunSensor(coordinator, data, element)
    if element.kind == WINDOW:
        return SolarGainSensor(coordinator, data, element)
    if element.kind == INTERNAL_WALL:
        return TemperatureDifferenceSensor(data, element)
    if element.kind == ROOM:
        return RoomSolarGainSensor(coordinator, data, element)
    return None


def _light(coordinator: SkyCoordinator, element: Element) -> float | None:
    """Light on the part's plane now, W/m2."""
    sky = coordinator.now()
    if sky is None or element.plane is None:
        return None
    hass = coordinator.hass
    azimuth, elevation = sun_position(
        sky.middle, hass.config.latitude, hass.config.longitude
    )
    return element.plane.light(sky.direct_normal, sky.diffuse, azimuth, elevation)


class _PartSensor(PartEntity, SensorEntity):
    """A sensor on one part's device."""

    _attr_state_class = SensorStateClass.MEASUREMENT


class SunSensor(CoordinatorEntity[SkyCoordinator], _PartSensor):
    """The sun and sky light on an outside wall or roof."""

    _attr_device_class = SensorDeviceClass.IRRADIANCE
    _attr_native_unit_of_measurement = UnitOfIrradiance.WATTS_PER_SQUARE_METER
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: SkyCoordinator, data: HouseData, element: Element
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        _PartSensor.__init__(self, data, element, "solar_exposure")

    @property
    def native_value(self) -> float | None:
        return _light(self.coordinator, self.element)

    @property
    def extra_state_attributes(self) -> dict:
        return self.element.attributes()


def _open(hass: HomeAssistant, window: Element) -> float | None:
    """How open a window's blind is; ``None`` if it cannot be read."""
    if not window.blind:
        return 1.0
    state = hass.states.get(window.blind)
    if state is None:
        return None
    return blind_open_fraction(state.state, state.attributes.get("current_position"))


def _window_watts(coordinator: SkyCoordinator, window: Element) -> float | None:
    """The sun's heat through a window now; a blind that cannot be read is open."""
    light = _light(coordinator, window)
    if light is None or not window.size_m2:
        return None
    opened = _open(coordinator.hass, window)
    return window_gain(
        light,
        window.size_m2,
        window.transmittance,
        1.0 if opened is None else opened,
        window.blind_closed,
    )


class SolarGainSensor(CoordinatorEntity[SkyCoordinator], _PartSensor):
    """The sun's heat through a window, less what its blind keeps out."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: SkyCoordinator, data: HouseData, element: Element
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        _PartSensor.__init__(self, data, element, "solar_gain")

    def watched(self) -> list[str | None]:
        return [self.element.blind]

    @property
    def native_value(self) -> float | None:
        return _window_watts(self.coordinator, self.element)

    @property
    def extra_state_attributes(self) -> dict:
        out = self.element.attributes()
        out["light_w_m2"] = _round(_light(self.coordinator, self.element))
        if self.element.blind:
            # when the blind cannot be read it is taken as open
            out["blind_open"] = _round(_open(self.hass, self.element), 2)
        return out


class RoomSolarGainSensor(CoordinatorEntity[SkyCoordinator], _PartSensor):
    """The sun's heat through all of a room's windows."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: SkyCoordinator, data: HouseData, room: Element
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        _PartSensor.__init__(self, data, room, "solar_gain")

    @property
    def windows(self) -> list[Element]:
        """The room's windows, as the parts are now."""
        return windows_in(self.data.elements, self.element.area_id)

    def watched(self) -> list[str | None]:
        return [w.blind for w in self.windows]

    @property
    def native_value(self) -> float | None:
        if not self.windows:
            return 0.0
        watts = [_window_watts(self.coordinator, w) for w in self.windows]
        if any(w is None for w in watts):
            return None
        return sum(watts)

    @property
    def extra_state_attributes(self) -> dict:
        out = self.element.attributes()
        out["windows"] = [w.title for w in self.windows]
        # from both sides: rooms that list this one count too
        out["neighbours"] = neighbours(self.data.elements).get(self.element.area_id, [])
        out["glass_m2"] = round(sum(w.size_m2 or 0.0 for w in self.windows), 3)
        return out


class TemperatureDifferenceSensor(_PartSensor):
    """This room's temperature minus the room on the other side of the wall."""

    _attr_should_poll = False
    _attr_suggested_display_precision = 1

    def __init__(self, data: HouseData, element: Element) -> None:
        super().__init__(data, element, "temperature_difference")
        self._sides: tuple[str | None, str | None] = (None, None)

    async def async_added_to_hass(self) -> None:
        self._attr_native_unit_of_measurement = self.hass.config.units.temperature_unit
        await super().async_added_to_hass()

    def watched(self) -> list[str | None]:
        # looked up again whenever the part changes
        self._sides = (
            area_temperature(self.hass, self.element.area_id),
            area_temperature(self.hass, self.element.other_area_id),
        )
        return list(self._sides)

    def _reading(self, entity_id: str | None) -> float | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    @property
    def native_value(self) -> float | None:
        this, other = (self._reading(s) for s in self._sides)
        if this is None or other is None:
            return None
        return this - other

    @property
    def extra_state_attributes(self) -> dict:
        out = self.element.attributes()
        out["temperature_entity"], out["other_temperature_entity"] = self._sides
        if None in self._sides:
            out["problem"] = (
                "Choose a temperature sensor in the area's settings for each room"
            )
        return out


class OutlineSensor(SensorEntity):
    """Whether the building outline was found, for the house's device.

    ``found`` once OpenStreetMap (or the saved copy) gave the building,
    ``not_found`` when it answered with no building at the home position,
    ``failed`` when it could not be reached (the next setup tries again) and
    ``not_loaded`` before it has been looked up. Sun Sweep draws its plain
    square unless this is ``found``.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["found", "not_found", "failed", "not_loaded"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_outline"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="House Structure",
            model="House",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, OUTLINE_SIGNAL, self._changed)
        )

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def _info(self) -> dict | None:
        return self.hass.data.get(OUTLINE)

    @property
    def native_value(self) -> str:
        info = self._info
        if info is None:
            return "not_loaded"
        if info.get("failed"):
            return "failed"
        return "found" if info.get("points") else "not_found"

    @property
    def extra_state_attributes(self) -> dict:
        info = self._info or {}
        if not info.get("points"):
            return {}
        return {"corners": len(info["points"]), "rotation": info.get("rotation")}


def _round(value: float | None, digits: int = 0) -> float | None:
    return None if value is None else round(value, digits)
