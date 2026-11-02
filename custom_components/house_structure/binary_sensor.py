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
from homeassistant.core import Event, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event

from .constants import DOMAIN, REGISTER
from .devices import HouseData
from .model import Element


async def async_setup_entry(hass, entry, async_add_entities):
    """A heating sensor for each register."""
    data: HouseData = entry.runtime_data
    for element in data.elements.values():
        if element.kind == REGISTER:
            async_add_entities(
                [RegisterHeatingSensor(element)], config_subentry_id=element.id
            )


class RegisterHeatingSensor(BinarySensorEntity):
    """On while the register's thermostat is heating."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_translation_key = "heating"

    def __init__(self, element: Element) -> None:
        self.element = element
        self._attr_unique_id = f"{element.id}_heating"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, element.id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        tracked = [e for e in (self.element.climate, self.element.fan) if e]
        if tracked:
            self.async_on_remove(
                async_track_state_change_event(self.hass, tracked, self._changed)
            )

    @callback
    def _changed(self, event: Event) -> None:
        self.async_write_ha_state()

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
