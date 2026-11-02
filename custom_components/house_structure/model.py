# Copyright (c) 2026 MinchinWeb
"""The house as a set of elements: rooms, walls, roofs, windows, internal walls
and heating registers.

Each element is one sub-entry of the integration and sits in one Home Assistant
area (a room). A window takes its plane and its room from the wall or roof it
is in. Sizes are stored in metres. Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import NamedTuple

from .constants import INTERNAL_WALL, REGISTER, ROOF, ROOM, WALL, WINDOW
from .geometry import Plane, face_azimuth

# Defaults for a window: the share of the light double glazing lets in as
# heat, and the share a closed blind still lets through.
TRANSMITTANCE = 0.7
BLIND_CLOSED = 0.2


class Raw(NamedTuple):
    """One sub-entry as Home Assistant stores it."""

    id: str
    kind: str
    title: str
    data: dict


@dataclass(frozen=True)
class Element:
    """One part of the house.

    Attributes:
        id: The sub-entry id.
        kind: ``room``, ``wall``, ``roof``, ``window``, ``internal_wall`` or
            ``register``.
        title: Its name.
        area_id: The room it belongs to (for a window, its host's room).
        plane: The surface the sun shines on; ``None`` for an internal wall.
        size_m2: Its area (glass for a window), if the sizes were given.
        host: For a window, the wall or roof it is in.
        other_area_id: For an internal wall, the room on the other side.
        transmittance: For a window, the share of light let in as heat.
        blind: For a window, the cover entity of its blind.
        blind_closed: For a window, the share a closed blind lets through.
        glass_m2: For a wall or roof, the glass of the windows in it.
        floor_m2: For a room, its floor area.
        height_m: For a room, its ceiling height.
        volume_m3: For a room, its air volume (given, or floor times height).
        below_ground: For a room, whether its walls are (partly) in the soil.
        climate: For a register, the thermostat that calls for its heat.
        fan: For a register, its own fan or damper, if it has one.
    """

    id: str
    kind: str
    title: str
    area_id: str | None
    plane: Plane | None = None
    size_m2: float | None = None
    host: str | None = None
    other_area_id: str | None = None
    transmittance: float = TRANSMITTANCE
    blind: str | None = None
    blind_closed: float = BLIND_CLOSED
    glass_m2: float = 0.0
    floor_m2: float | None = None
    height_m: float | None = None
    volume_m3: float | None = None
    below_ground: bool = False
    climate: str | None = None
    fan: str | None = None

    @property
    def net_m2(self) -> float | None:
        """A wall's or roof's area without its windows."""
        if self.size_m2 is None:
            return None
        return max(self.size_m2 - self.glass_m2, 0.0)

    def attributes(self) -> dict:
        """What other integrations need to know about the element."""
        out: dict = {"kind": self.kind, "area_id": self.area_id}
        if self.plane is not None:
            out["azimuth"] = round(self.plane.azimuth, 1)
            out["tilt"] = round(self.plane.tilt, 1)
        if self.size_m2 is not None:
            out["area_m2"] = round(self.size_m2, 3)
        if self.kind in (WALL, ROOF):
            out["glass_m2"] = round(self.glass_m2, 3)
            if self.net_m2 is not None:
                out["net_m2"] = round(self.net_m2, 3)
        if self.kind == WINDOW:
            out["host"] = self.host
            out["transmittance"] = self.transmittance
            if self.blind:
                out["blind"] = self.blind
                out["blind_closed"] = self.blind_closed
        if self.kind == INTERNAL_WALL:
            out["other_area_id"] = self.other_area_id
        if self.kind == ROOM:
            for key in ("floor_m2", "height_m", "volume_m3"):
                if getattr(self, key) is not None:
                    out[key] = round(getattr(self, key), 3)
            out["below_ground"] = self.below_ground
        if self.kind == REGISTER:
            out["climate"] = self.climate
            if self.fan:
                out["fan"] = self.fan
        return out


def _area(data: dict, width: str, height: str) -> float | None:
    a, b = data.get(width), data.get(height)
    if a is None or b is None:
        return None
    return float(a) * float(b)


def _plane(data: dict, house: dict, tilt: float) -> Plane:
    rotation = float(house.get("rotation") or 0.0)
    if data.get("facing") is not None:
        azimuth = float(data["facing"]) % 360.0
    else:
        azimuth = face_azimuth(data.get("face", "S"), rotation)
    shade = data.get("shade_below")
    if shade is None:
        shade = house.get("shade_below") or 0.0
    return Plane(azimuth, tilt, float(shade))


def build(house: dict, raws: list[Raw]) -> tuple[dict[str, Element], list[str]]:
    """Turn the sub-entries into elements.

    Args:
        house: The integration's own settings (``rotation``, ``shade_below``).
        raws: Its sub-entries.

    Returns:
        The elements by id, and a note for each sub-entry that was skipped.
    """
    elements: dict[str, Element] = {}
    problems: list[str] = []
    rooms: set[str] = set()
    for raw in raws:
        d = raw.data
        if raw.kind == ROOM:
            area = d.get("area_id")
            if area in rooms:
                problems.append(f"{raw.title}: its area already has a room")
                continue
            rooms.add(area)
            floor, height = d.get("floor_m2"), d.get("height_m")
            volume = d.get("volume_m3")
            if volume is None and floor is not None and height is not None:
                volume = float(floor) * float(height)
            elements[raw.id] = Element(
                raw.id,
                ROOM,
                raw.title,
                area,
                floor_m2=floor,
                height_m=height,
                volume_m3=volume,
                below_ground=bool(d.get("below_ground", False)),
            )
        elif raw.kind == REGISTER:
            elements[raw.id] = Element(
                raw.id,
                REGISTER,
                raw.title,
                d.get("area_id"),
                climate=d.get("climate"),
                fan=d.get("fan") or None,
            )
        elif raw.kind == WALL:
            elements[raw.id] = Element(
                raw.id,
                WALL,
                raw.title,
                d.get("area_id"),
                plane=_plane(d, house, 90.0),
                size_m2=_area(d, "length_m", "height_m"),
            )
        elif raw.kind == ROOF:
            elements[raw.id] = Element(
                raw.id,
                ROOF,
                raw.title,
                d.get("area_id"),
                plane=_plane(d, house, float(d.get("pitch", 45.0))),
                size_m2=_area(d, "length_m", "slope_m"),
            )
        elif raw.kind == INTERNAL_WALL:
            elements[raw.id] = Element(
                raw.id,
                INTERNAL_WALL,
                raw.title,
                d.get("area_id"),
                size_m2=_area(d, "length_m", "height_m"),
                other_area_id=d.get("other_area_id"),
            )
    for raw in raws:
        if raw.kind != WINDOW:
            continue
        d = raw.data
        host = elements.get(d.get("host", ""))
        if host is None or host.plane is None:
            problems.append(f"{raw.title}: the wall or roof it is in was removed")
            continue
        glass = _area(d, "width_m", "height_m")
        elements[raw.id] = Element(
            raw.id,
            WINDOW,
            raw.title,
            host.area_id,
            plane=host.plane,
            size_m2=glass,
            host=host.id,
            transmittance=float(d.get("transmittance", TRANSMITTANCE)),
            blind=d.get("blind") or None,
            blind_closed=float(d.get("blind_closed", BLIND_CLOSED)),
        )
        if glass:
            elements[host.id] = replace(
                elements[host.id], glass_m2=elements[host.id].glass_m2 + glass
            )
    return elements, problems


def windows_in(elements: dict[str, Element], area_id: str | None) -> list[Element]:
    """The windows of a room."""
    return [e for e in elements.values() if e.kind == WINDOW and e.area_id == area_id]


# The version of the room summary other integrations read; raise it when a key
# changes meaning or goes away (adding keys does not need it).
SUMMARY_VERSION = 1


def _plane_summary(element: Element) -> dict:
    plane = element.plane
    return {
        "title": element.title,
        "azimuth": round(plane.azimuth, 2),
        "tilt": round(plane.tilt, 2),
        "shade_below": plane.shade_below,
    }


def _empty_room(area_id: str, temperature: str | None) -> dict:
    return {
        "area_id": area_id,
        "title": None,
        "floor_m2": None,
        "height_m": None,
        "volume_m3": None,
        "below_ground": False,
        "temperature_entity": temperature,
        "windows": [],
        "walls": [],
        "roofs": [],
        "internal_walls": [],
        "registers": [],
    }


def rooms_summary(
    elements: dict[str, Element], temperature: dict[str, str | None] | None = None
) -> dict[str, dict]:
    """Each room's parts as plain data, by area id, for other integrations.

    Every area with a part is a room, with or without a room part. Planes are
    compass azimuths and tilts in degrees; areas in m2. An internal wall is
    listed in the rooms on both sides.

    Args:
        elements: The parts, from ``build``.
        temperature: The temperature sensor of each area, where known.
    """
    temperature = temperature or {}
    rooms: dict[str, dict] = {}

    def room(area_id: str | None) -> dict | None:
        if not area_id:
            return None
        if area_id not in rooms:
            rooms[area_id] = _empty_room(area_id, temperature.get(area_id))
        return rooms[area_id]

    for e in elements.values():
        here = room(e.area_id)
        if here is None:
            continue
        if e.kind == ROOM:
            here.update(
                title=e.title,
                floor_m2=e.floor_m2,
                height_m=e.height_m,
                volume_m3=e.volume_m3,
                below_ground=e.below_ground,
            )
        elif e.kind in (WALL, ROOF):
            here["walls" if e.kind == WALL else "roofs"].append(
                {**_plane_summary(e), "area_m2": e.size_m2, "glass_m2": e.glass_m2}
            )
        elif e.kind == WINDOW:
            here["windows"].append(
                {
                    **_plane_summary(e),
                    "in": elements[e.host].kind,
                    "glass_m2": e.size_m2,
                    "transmittance": e.transmittance,
                    "blind": e.blind,
                    "blind_closed": e.blind_closed,
                }
            )
        elif e.kind == INTERNAL_WALL:
            for this, other in (
                (e.area_id, e.other_area_id),
                (e.other_area_id, e.area_id),
            ):
                side = room(this)
                if side is not None:
                    side["internal_walls"].append(
                        {"title": e.title, "other_area_id": other, "area_m2": e.size_m2}
                    )
        elif e.kind == REGISTER:
            here["registers"].append(
                {"title": e.title, "climate": e.climate, "fan": e.fan}
            )
    return rooms
