# Copyright (c) 2026 MinchinWeb
"""One device per part of the house, kept in the part's area, and the rooms
published for other integrations.

Other integrations read ``hass.data["house_structure"]``: ``{"version": 1,
"rooms": {area_id: summary}}`` (see ``model.rooms_summary``), and listen for
the ``house_structure_updated`` event, fired when the summary changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .constants import (
    DOMAIN,
    INTERNAL_WALL,
    REGISTER,
    ROOF,
    ROOM,
    UPDATED_EVENT,
    WALL,
    WINDOW,
)
from .coordinator import SkyCoordinator
from .model import SUMMARY_VERSION, Element, Raw, build, rooms_summary

_LOGGER = logging.getLogger(__name__)

_MODELS = {
    ROOM: "Room",
    WALL: "Outside wall",
    ROOF: "Roof",
    WINDOW: "Window",
    INTERNAL_WALL: "Internal wall",
    REGISTER: "Heating register",
}


@dataclass
class HouseData:
    """What the platforms share: the sky and the parts of the house.

    Attributes:
        coordinator: The sky.
        elements: The parts, by id; replaced when a part changes.
        house: The house settings the entry was set up with; when they change
            the entry is reloaded instead.
    """

    coordinator: SkyCoordinator
    elements: dict[str, Element]
    house: dict


def elements_of(entry) -> dict[str, Element]:
    """The parts of the house from the entry's sub-entries."""
    raws = [
        Raw(s.subentry_id, s.subentry_type, s.title, dict(s.data))
        for s in entry.subentries.values()
    ]
    elements, problems = build(dict(entry.data), raws)
    for problem in problems:
        _LOGGER.warning("Skipping %s", problem)
    return elements


def register_devices(hass, entry, elements: dict[str, Element]) -> None:
    """Make a device for each part and put it in the part's area.

    The part's settings choose its room and name; a device moved by hand goes
    back when the parts next change.
    """
    devices = dr.async_get(hass)
    areas = ar.async_get(hass)
    for element in elements.values():
        device = devices.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=element.id,
            identifiers={(DOMAIN, element.id)},
            name=element.title,
            manufacturer="House Structure",
            model=_MODELS[element.kind],
        )
        if element.area_id and device.area_id != element.area_id:
            if areas.async_get_area(element.area_id) is None:
                _LOGGER.warning("%s: its area was deleted", element.title)
            else:
                devices.async_update_device(device.id, area_id=element.area_id)


def area_temperature(hass: HomeAssistant, area_id: str | None) -> str | None:
    """A room's temperature sensor.

    The one chosen in the area's settings, else the area's only temperature
    sensor (on its own or on one of the area's devices).
    """
    if not area_id:
        return None
    area = ar.async_get(hass).async_get_area(area_id)
    if area is None:
        return None
    chosen = getattr(area, "temperature_entity_id", None)
    if chosen:
        return chosen
    entities = er.async_get(hass)
    found = set()
    candidates = list(er.async_entries_for_area(entities, area_id))
    for device in dr.async_entries_for_area(dr.async_get(hass), area_id):
        candidates += [
            e
            for e in er.async_entries_for_device(entities, device.id)
            if e.area_id is None
        ]
    for entry in candidates:
        device_class = entry.device_class or entry.original_device_class
        if (
            entry.domain == "sensor"
            and device_class == SensorDeviceClass.TEMPERATURE
            and entry.disabled_by is None
            and entry.platform != DOMAIN
        ):
            found.add(entry.entity_id)
    return found.pop() if len(found) == 1 else None


def publish_rooms(hass: HomeAssistant, elements: dict[str, Element] | None) -> None:
    """Share the rooms' parts, and tell listeners when they changed.

    ``None`` takes the rooms away (the integration was removed).
    """
    rooms: dict = {}
    if elements is not None:
        areas = {a for e in elements.values() for a in e.area_ids}
        areas |= {e.other_area_id for e in elements.values()}
        temperature = {a: area_temperature(hass, a) for a in areas if a}
        rooms = rooms_summary(elements, temperature)
    old = hass.data.get(DOMAIN, {}).get("rooms")
    hass.data[DOMAIN] = {"version": SUMMARY_VERSION, "rooms": rooms}
    if old != rooms:
        hass.bus.async_fire(UPDATED_EVENT, {"rooms": sorted(rooms)})
