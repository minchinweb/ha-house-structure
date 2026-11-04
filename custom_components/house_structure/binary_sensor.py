# Copyright (c) 2026 MinchinWeb
"""Whether each heating register is delivering heat, and whether each door is
open.

A register is on while the thermostat it hangs off is heating (its
``hvac_action``). Its fan, if it has one, is given in the attributes: the
register still delivers heat with the fan off, only less of it.

A door with a contact sensor is on while the contact is (open). It follows the
contact, and adds the door's place in the house: its wall, the rooms on each
side and their temperature sensors, so a door's state can be read with the
rooms it joins.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .constants import DOOR, REGISTER
from .devices import HouseData, area_temperature
from .entity import PartEntity, setup_parts
from .model import Element


async def async_setup_entry(hass, entry, async_add_entities):
    """A heating sensor for each register, and an open sensor for each door
    with a contact, now and as they are added."""
    setup_parts(hass, entry, async_add_entities, _sensor_for)


def _sensor_for(data: HouseData, element: Element) -> PartEntity | None:
    if element.kind == REGISTER:
        return RegisterHeatingSensor(data, element)
    if element.kind == DOOR and element.sensor:
        return DoorOpenSensor(data, element)
    return None


class RegisterHeatingSensor(PartEntity, BinarySensorEntity):
    """On while the register's thermostat is heating."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, data: HouseData, element: Element) -> None:
        super().__init__(data, element, "heating")

    def watched(self) -> list[str | None]:
        return [self.element.climate, self.element.fan]

    @property
    def is_on(self) -> bool | None:
        state = self.hass.states.get(self.element.climate or "")
        if state is None:
            return None
        action = state.attributes.get("hvac_action")
        if action is None:
            return None
        return action == "heating"

    @property
    def extra_state_attributes(self) -> dict:
        out = self.element.attributes()
        if self.element.fan:
            fan = self.hass.states.get(self.element.fan)
            out["fan_on"] = None if fan is None else fan.state == "on"
        return out


class DoorOpenSensor(PartEntity, BinarySensorEntity):
    """On while the door's contact sensor is on (open)."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, data: HouseData, element: Element) -> None:
        super().__init__(data, element, "door")

    def watched(self) -> list[str | None]:
        return [self.element.sensor]

    @property
    def is_on(self) -> bool | None:
        state = self.hass.states.get(self.element.sensor or "")
        if state is None or state.state not in ("on", "off"):
            return None  # no sensor, or it is unknown or unavailable
        return state.state == "on"

    @property
    def extra_state_attributes(self) -> dict:
        out = self.element.attributes()
        host = self.data.elements.get(self.element.host or "")
        if host is not None:
            out["wall"] = host.title
        # each side's temperature sensor, so a door's state can be read with them
        out["temperature_entity"] = area_temperature(self.hass, self.element.area_id)
        out["other_temperature_entity"] = area_temperature(
            self.hass, self.element.other_area_id
        )
        return out
