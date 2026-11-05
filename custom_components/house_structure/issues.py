# Copyright (c) 2026 MinchinWeb
"""Repairs for what the house is missing, raised only when something needs it.

House Structure's own sensors work without the sizes of walls, roofs and
rooms, so a missing size isn't a problem on its own. It becomes one when
another integration uses that number: Manual J needs every wall's size for
its heat loss, for instance. Such an integration says what it needs in
``hass.data["house_structure_needs"]`` and fires
``house_structure_needs_updated``:

.. code-block:: python

    needs = hass.data.setdefault("house_structure_needs", {})
    needs["manual_j"] = {
        "title": "Manual J",
        "needs": ["wall_size", "roof_size", "room_floor"],
    }
    hass.bus.async_fire("house_structure_needs_updated")

It removes its entry, and fires the event again, when it unloads. The needs
are the keys of ``NEEDS_KEYS``. Each repair names the integrations that need
the number, links to the part's device, and for a wall or roof names its room
(linked to the area). The repairs are kept in step with the parts and the
needs: a fixed one goes away when either next changes.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import issue_registry as ir

from .constants import DOMAIN, NEEDS, ROOF, ROOM, WALL
from .devices import part_device

# What another integration can ask for: (kind of part, its attribute).
NEEDS_KEYS = {
    "wall_size": (WALL, "size_m2"),
    "roof_size": (ROOF, "size_m2"),
    "room_floor": (ROOM, "floor_m2"),
}
# the repair's translation key for each need
_KEYS = {
    "wall_size": "missing_wall_size",
    "roof_size": "missing_roof_size",
    "room_floor": "missing_floor",
}


def _issue_id(entry_id: str, part_id: str) -> str:
    return f"{entry_id}:{part_id}"


def _link(text: str, url: str) -> str:
    return f"[{text}]({url})"


def needed_by(registry: dict | None) -> dict[str, list[str]]:
    """Each need, and the titles of the integrations that have it, sorted.

    Args:
        registry: ``hass.data["house_structure_needs"]``. Entries that aren't
            a dict, and needs that aren't in ``NEEDS_KEYS``, are ignored.
    """
    out: dict[str, set[str]] = {}
    for key, entry in (registry or {}).items():
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or key)
        for need in entry.get("needs") or ():
            if need in NEEDS_KEYS:
                out.setdefault(need, set()).add(title)
    return {need: sorted(titles) for need, titles in out.items()}


def missing(elements: dict, needs: dict[str, list[str]]) -> dict[str, tuple[str, str]]:
    """The parts that lack a number something needs.

    Returns:
        By part id: the need (a key of ``NEEDS_KEYS``) and who needs it, as
        text ("Home Thermal Lab and Manual J").
    """
    out = {}
    for element in elements.values():
        for need, (kind, attribute) in NEEDS_KEYS.items():
            titles = needs.get(need)
            if titles and element.kind == kind and getattr(element, attribute) is None:
                out[element.id] = (need, " and ".join(titles))
    return out


def _placeholders(
    hass: HomeAssistant, entry_id: str, element, who: str
) -> dict[str, str]:
    """The part as a link to its device, its room(s) as links, and who needs it."""
    device = part_device(hass, entry_id, element.id)
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
    return {"part": part, "room": room, "needed_by": who}


def check(hass: HomeAssistant, entry_id: str, elements: dict) -> None:
    """Raise a repair for each needed size that's missing; clear the rest."""
    needs = needed_by(hass.data.get(NEEDS))
    wanted: dict[str, tuple[str, dict[str, str]]] = {}
    for part_id, (need, who) in missing(elements, needs).items():
        wanted[_issue_id(entry_id, part_id)] = (
            _KEYS[need],
            _placeholders(hass, entry_id, elements[part_id], who),
        )

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
