# Copyright (c) 2026 MinchinWeb
"""Sensors on each part of the house (see ``devices.py`` for the devices).

* Wall and roof: ``sun``, the light on it (W/m2).
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .constants import INTERNAL_WALL, ROOF, ROOM, WALL, WINDOW
from .coordinator import SkyCoordinator
from .devices import HouseData, area_temperature
from .entity import PartEntity, setup_parts
from .geometry import blind_open_fraction, window_gain
from .model import Element, windows_in
from .sun import sun_position

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Create each part's sensors on its device, now and as parts are added."""
    setup_parts(hass, entry, async_add_entities, _sensor_for)


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
        _PartSensor.__init__(self, data, element, "sun")

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


def _round(value: float | None, digits: int = 0) -> float | None:
    return None if value is None else round(value, digits)
