# Copyright (c) 2026 MinchinWeb
"""Diagnostics: the whole house as saved and as built, to check or share.

Download it from the integration's menu. It gives the house settings, each
part's settings (sizes in metres, whatever unit the forms show) with what was
built from them, any parts that were skipped, every area with the parts in it
(so an area with none stands out) and the areas beside, above and below it,
the sky now, and the OpenStreetMap outline as wall bearings and lengths only.
Nothing in it says where the house is.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import floor_registry as fr

from .constants import OUTLINE
from .devices import part_device
from .model import Raw, build, neighbours
from .orientation import outline_walls, wall_rotation


def house_layout(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    include_sheet: bool = True,
    include_entities: bool = False,
) -> dict[str, Any]:
    """The house layout: settings, parts, areas and (optionally) the CSV sheet.

    Used by the ``house_structure/layout`` websocket command and by diagnostics.
    Nothing in it says where the house is. Entity states and sky readings are
    left out unless ``include_entities`` is true (diagnostics).
    """
    raws = [
        Raw(s.subentry_id, s.subentry_type, s.title, dict(s.data))
        for s in entry.subentries.values()
    ]
    elements, skipped = build(dict(entry.data), raws)
    areas = ar.async_get(hass)
    floors = fr.async_get(hass)
    entities = er.async_get(hass) if include_entities else None

    def floor_of(area_id: str | None) -> str | None:
        area = areas.async_get_area(area_id) if area_id else None
        floor = (
            floors.async_get_floor(area.floor_id) if area and area.floor_id else None
        )
        return floor.name if floor else None

    def area_name(area_id: str | None) -> str | None:
        area = areas.async_get_area(area_id) if area_id else None
        return area.name if area else None

    parts = []
    for raw in raws:
        element = elements.get(raw.id)
        part: dict[str, Any] = {
            "id": raw.id,
            "kind": raw.kind,
            "title": raw.title,
            "settings": raw.data,
            "built": element.attributes() if element else None,
        }
        if element:
            part["area"] = area_name(element.area_id)
            part["floor"] = floor_of(element.area_id)
        if include_entities:
            device = part_device(hass, entry.entry_id, raw.id)
            if device:
                part["device_area"] = area_name(device.area_id)
                part["entities"] = [
                    _entity(hass, e.entity_id)
                    for e in er.async_entries_for_device(entities, device.id)
                ]
        parts.append(part)

    in_area: dict[str, list[str]] = {}
    for element in elements.values():
        for area_id in element.area_ids or (element.area_id,):
            if area_id:
                in_area.setdefault(area_id, []).append(
                    f"{element.kind}: {element.title}"
                )

    links = neighbours(elements)
    out: dict[str, Any] = {
        "house": dict(entry.data),
        "options": dict(entry.options),
        "skipped": skipped,
        "parts": parts,
        "areas": [
            {
                "area_id": area.id,
                "name": area.name,
                "floor": floor_of(area.id),
                "parts": sorted(in_area.get(area.id, [])),
                "neighbours": [
                    f"{n['position']}: {area_name(n['area_id'])}"
                    for n in links.get(area.id, [])
                ],
            }
            for area in areas.async_list_areas()
        ],
        "outline": _outline(hass),
    }
    if include_sheet:
        # imported here so layout stays usable in tests that never open the form
        from .sheet_flow import export_sheet

        out["sheet"] = export_sheet(hass, entry)
    return out


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """The house, its parts and its areas."""
    data = house_layout(hass, entry, include_sheet=False, include_entities=True)
    data["sky"] = _sky(entry)
    return data


def _entity(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    state = hass.states.get(entity_id)
    return {
        "entity_id": entity_id,
        "state": state.state if state else None,
        "unit": state.attributes.get("unit_of_measurement") if state else None,
    }


def _sky(entry: ConfigEntry) -> dict[str, Any] | None:
    data = getattr(entry, "runtime_data", None)
    if data is None:
        return None
    coordinator = data.coordinator
    now = coordinator.now()
    return {
        "source": type(coordinator).__name__,
        "last_update_success": coordinator.last_update_success,
        "readings": len(coordinator.data or []),
        "now": None
        if now is None
        else {
            "time": now.time.isoformat(),
            "direct_normal": round(now.direct_normal, 1),
            "diffuse": round(now.diffuse, 1),
        },
    }


def _outline(hass: HomeAssistant) -> dict[str, Any] | None:
    """The outline the house form measured, if it has run since the restart."""
    points = hass.data.get(OUTLINE, {}).get("points")
    if not points:
        return None
    turn, squareness = wall_rotation(points)
    return {
        "rotation": round(turn, 1),
        "squareness": round(squareness, 3),
        "walls": [
            {"facing": facing, "length_m": length}
            for facing, length in outline_walls(points)
        ],
    }
