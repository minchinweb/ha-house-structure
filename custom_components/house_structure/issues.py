# Copyright (c) 2026 MinchinWeb
"""Repairs for what the house is missing, so the setup can be checked.

A wall or roof with no size, and a room with no floor area, each raise a
repair in Settings > Repairs. The repairs are kept in step with the parts: a
fixed one goes away when the house next changes.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .constants import DOMAIN, ROOF, ROOM, WALL

# the translation key for each kind of part's missing size
_KEYS = {WALL: "missing_wall_size", ROOF: "missing_roof_size", ROOM: "missing_floor"}


def _issue_id(entry_id: str, part_id: str) -> str:
    return f"{entry_id}:{part_id}"


def check(hass: HomeAssistant, entry_id: str, elements: dict) -> None:
    """Raise a repair for each missing size, and clear the rest for this entry."""
    wanted: dict[str, tuple[str, str]] = {}
    for element in elements.values():
        if element.kind in (WALL, ROOF) and element.size_m2 is None:
            key = _KEYS[element.kind]
            wanted[_issue_id(entry_id, element.id)] = (key, element.title)
        elif element.kind == ROOM and element.floor_m2 is None:
            name = element.area_id or element.title
            wanted[_issue_id(entry_id, element.id)] = (_KEYS[ROOM], name)

    registry = ir.async_get(hass)
    prefix = f"{entry_id}:"
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    for issue_id, (key, part) in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={"part": part},
        )
