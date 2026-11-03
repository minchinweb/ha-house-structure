# Copyright (c) 2026 MinchinWeb
"""Repairs for what the house is missing, so the setup can be checked.

A wall or roof with no size, and a room with no floor area, each raise a
repair in Settings > Repairs. The repairs are kept in step with the parts: a
fixed one goes away when the house next changes.

Each repair links to the part's device, and a wall or roof also names its
room (linked to the area), so the repair says where to look.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .constants import DOMAIN, ROOF, ROOM, WALL

# the translation key for each kind of part's missing size
_KEYS = {WALL: "missing_wall_size", ROOF: "missing_roof_size", ROOM: "missing_floor"}


def _issue_id(entry_id: str, part_id: str) -> str:
    return f"{entry_id}:{part_id}"


def _link(text: str, url: str) -> str:
    return f"[{text}]({url})"


def _placeholders(hass: HomeAssistant, element) -> dict[str, str]:
    """The part as a link to its device, and its room(s) as links to the areas."""
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, element.id)})
    part = element.title
    if device is not None:
        part = _link(element.title, f"/config/devices/device/{device.id}")

    areas = ar.async_get(hass)
    names = []
    for area_id in element.area_ids or ((element.area_id,) if element.area_id else ()):
        area = areas.async_get_area(area_id)
        if area is not None:
            names.append(_link(area.name, f"/config/areas/area/{area.id}"))
    # a wall or roof names its room(s); the empty phrase reads cleanly without one
    room = f"in {' and '.join(names)}" if names and element.kind != ROOM else ""
    return {"part": part, "room": room}


def check(hass: HomeAssistant, entry_id: str, elements: dict) -> None:
    """Raise a repair for each missing size, and clear the rest for this entry."""
    wanted: dict[str, tuple[str, dict[str, str]]] = {}
    for element in elements.values():
        if element.kind in (WALL, ROOF) and element.size_m2 is None:
            key = _KEYS[element.kind]
        elif element.kind == ROOM and element.floor_m2 is None:
            key = _KEYS[ROOM]
        else:
            continue
        wanted[_issue_id(entry_id, element.id)] = (key, _placeholders(hass, element))

    registry = ir.async_get(hass)
    prefix = f"{entry_id}:"
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    for issue_id, (key, placeholders) in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=placeholders,
        )
