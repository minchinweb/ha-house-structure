# Copyright (c) 2026 MinchinWeb
"""Whether each heating register is delivering heat.

A register is on while the thermostat it hangs off is heating (its
``hvac_action``). Its fan, if it has one, is given in the attributes: the
register still delivers heat with the fan off, only less of it.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .constants import REGISTER
from .devices import HouseData
from .entity import PartEntity, setup_parts
from .model import Element


async def async_setup_entry(hass, entry, async_add_entities):
    """A heating sensor for each register, now and as registers are added."""
    setup_parts(hass, entry, async_add_entities, _sensor_for)


def _sensor_for(data: HouseData, element: Element) -> PartEntity | None:
    return RegisterHeatingSensor(data, element) if element.kind == REGISTER else None


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
