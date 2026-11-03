# Copyright (c) 2026 MinchinWeb
"""What every part's entity shares, and keeping them in step with the parts.

Adding, changing or removing a part does not reload the integration (that
would take every entity away for a moment, which fills the history with
"unavailable"). ``__init__.py`` rebuilds the parts and sends ``parts_signal``;
each platform then hands the new parts to its entities, which follow other
entities (blinds, thermostats, temperatures) afresh, and adds entities for new
parts. Home Assistant removes a removed part's device, and its entities with it.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from .constants import DOMAIN
from .devices import HouseData
from .model import Element


def parts_signal(entry_id: str) -> str:
    """The dispatcher signal sent when the parts of a house change."""
    return f"{DOMAIN}_parts_{entry_id}"


class PartEntity(Entity):
    """An entity on one part's device.

    Attributes:
        data: The house, whose ``elements`` are always the current parts.
        element: This part, as last built.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: HouseData, element: Element, key: str) -> None:
        self.data = data
        self.element = element
        self._attr_translation_key = key
        self._attr_unique_id = f"{element.id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, element.id)})
        self._stop_watching: CALLBACK_TYPE | None = None

    def watched(self) -> list[str | None]:
        """Other entities whose changes change this one."""
        return []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._watch()
        self.async_on_remove(self._unwatch)

    @callback
    def _watch(self) -> None:
        self._unwatch()
        if watched := sorted({e for e in self.watched() if e}):
            self._stop_watching = async_track_state_change_event(
                self.hass, watched, self._changed
            )

    @callback
    def _unwatch(self) -> None:
        if self._stop_watching is not None:
            self._stop_watching()
            self._stop_watching = None

    @callback
    def _changed(self, event: Event) -> None:
        self.async_write_ha_state()

    @callback
    def async_set_part(self, element: Element) -> None:
        """Take the part's new settings, and show them."""
        self.element = element
        if self.hass is None:  # not added yet; it reads them when it is
            return
        self._watch()
        self.async_write_ha_state()


def setup_parts(
    hass: HomeAssistant,
    entry,
    async_add_entities,
    make: Callable[[HouseData, Element], PartEntity | None],
) -> None:
    """Add an entity for each part ``make`` gives one, now and as parts come.

    Args:
        hass: Home Assistant.
        entry: The integration's config entry.
        async_add_entities: The platform's callback.
        make: The entity for a part, or ``None`` if the platform has none.
    """
    data: HouseData = entry.runtime_data
    entities: dict[str, PartEntity] = {}

    @callback
    def sync() -> None:
        for part_id in list(entities):
            if part_id in data.elements:
                entities[part_id].async_set_part(data.elements[part_id])
            else:
                # its device goes with the sub-entry, taking the entity along
                del entities[part_id]
        for element in data.elements.values():
            if element.id in entities:
                continue
            if (entity := make(data, element)) is not None:
                entities[element.id] = entity
                async_add_entities([entity], config_subentry_id=element.id)

    sync()
    entry.async_on_unload(
        async_dispatcher_connect(hass, parts_signal(entry.entry_id), sync)
    )
