# Copyright (c) 2026 MinchinWeb
"""The house as a set of elements: rooms, walls, roofs, windows, doors, internal
walls and heating registers.

Each element is one sub-entry of the integration and sits in a Home Assistant
area (a room). A roof may cover several rooms (``area_ids``); its device sits
in the first. A window takes its plane from the wall or roof it is in, and its
room too, unless it names one of a shared roof's rooms. A door is in an outside
or internal wall, and takes its room (and, in an internal wall, the room on the
other side) from it. Sizes are stored in metres. Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import NamedTuple

from .constants import DOOR, INTERNAL_WALL, REGISTER, ROOF, ROOM, WALL, WINDOW
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
        kind: ``room``, ``wall``, ``roof``, ``window``, ``door``,
            ``internal_wall`` or ``register``.
        title: Its name.
        area_id: The room it belongs to (for a window, its host's room unless
            it names one); for a roof, the first of its rooms.
        area_ids: Every room it belongs to: several for a shared roof.
        plane: The surface the sun shines on; ``None`` for an internal wall
            and a door in one.
        size_m2: Its area (glass for a window), if the sizes were given.
        host: For a window, the wall or roof it is in; for a door, the outside
            or internal wall it is in.
        other_area_id: For an internal wall, the room on the other side; for a
            door in one, the same (``None`` for a door to outside).
        transmittance: For a window, the share of light let in as heat.
        blind: For a window, the cover entity of its blind.
        blind_closed: For a window, the share a closed blind lets through.
        glass_m2: For a wall or roof, the glass of the windows in it.
        door_m2: For an outside or internal wall, the doors in it.
        sensor: For a door, its contact sensor (a binary sensor, on when open).
        floor_m2: For a room, its floor area.
        height_m: For a room, its ceiling height.
        volume_m3: For a room, its air volume (given, or floor times height).
        below_ground: For a room, whether its walls are (partly) in the soil.
        beside: For a room, the areas next to it on the same floor.
        above: For a room, the areas above its ceiling.
        climate: For a register, the thermostat that calls for its heat.
        fan: For a register, its own fan or damper, if it has one.
    """

    id: str
    kind: str
    title: str
    area_id: str | None
    area_ids: tuple[str, ...] = ()
    plane: Plane | None = None
    size_m2: float | None = None
    host: str | None = None
    other_area_id: str | None = None
    transmittance: float = TRANSMITTANCE
    blind: str | None = None
    blind_closed: float = BLIND_CLOSED
    glass_m2: float = 0.0
    door_m2: float = 0.0
    sensor: str | None = None
    floor_m2: float | None = None
    height_m: float | None = None
    volume_m3: float | None = None
    below_ground: bool = False
    beside: tuple[str, ...] = ()
    above: tuple[str, ...] = ()
    climate: str | None = None
    fan: str | None = None
    r_value_si: float | None = None
    glazing: str | None = None
    frame: str | None = None
    below_grade_m: float | None = None
    # For a room: whether ``below_grade_m`` is the house's default, not its own.
    below_grade_default: bool = False
    # For a wall: its length along the ground, and its face in the house's grid
    # (N, E, S or W: the nearest one when the wall sets its own bearing).
    length_m: float | None = None
    face: str | None = None
    free_area_in2: float | None = None
    flow_cfm: float | None = None
    duct: tuple[dict, ...] = ()
    # the shared duct section the register hangs off (its duct is the branch)
    upstream: str | None = None
    # For a door: its width and height (``width_m`` and ``height_m``).
    # For a room: its footprint (east to west, south to north), where its
    # south-west corner sits in the house grid, and its floor's height above
    # the ground. Metres; None when not given.
    width_m: float | None = None
    depth_m: float | None = None
    x_m: float | None = None
    y_m: float | None = None
    level_m: float | None = None
    # For a window: the glass's width and height.
    glass_width_m: float | None = None
    glass_height_m: float | None = None
    # For a register: its outlet, from its room's south-west corner, and its
    # height above the floor.
    at_x_m: float | None = None
    at_y_m: float | None = None
    at_z_m: float | None = None

    @property
    def net_m2(self) -> float | None:
        """A wall's or roof's area without its windows and doors."""
        if self.size_m2 is None:
            return None
        return max(self.size_m2 - self.glass_m2 - self.door_m2, 0.0)

    def __post_init__(self) -> None:
        if not self.area_ids and self.area_id:
            object.__setattr__(self, "area_ids", (self.area_id,))

    def attributes(self) -> dict:
        """What other integrations need to know about the element."""
        out: dict = {"kind": self.kind, "area_id": self.area_id}
        if self.kind == ROOF:
            out["area_ids"] = list(self.area_ids)
        if self.plane is not None:
            out["azimuth"] = round(self.plane.azimuth, 1)
            out["tilt"] = round(self.plane.tilt, 1)
        if self.size_m2 is not None:
            out["area_m2"] = round(self.size_m2, 3)
        if self.kind in (WALL, ROOF):
            out["glass_m2"] = round(self.glass_m2, 3)
            if self.kind == WALL:
                out["door_m2"] = round(self.door_m2, 3)
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
            out["door_m2"] = round(self.door_m2, 3)
        if self.kind == DOOR:
            out["host"] = self.host
            out["other_area_id"] = self.other_area_id
            out["sensor"] = self.sensor
        if self.kind == ROOM:
            for key in ("floor_m2", "height_m", "volume_m3"):
                if getattr(self, key) is not None:
                    out[key] = round(getattr(self, key), 3)
            out["below_ground"] = self.below_ground
            out["beside"] = list(self.beside)
            out["above"] = list(self.above)
        if self.kind == REGISTER:
            out["climate"] = self.climate
            if self.fan:
                out["fan"] = self.fan
        return out


def _optional(value) -> float | None:
    """A number from stored data, or None when it is missing."""
    return None if value in (None, "") else float(value)


def _area(data: dict, width: str, height: str) -> float | None:
    a, b = data.get(width), data.get(height)
    if a is None or b is None:
        return None
    return float(a) * float(b)


def _roof_area(
    data: dict, tilt: float, rooms: list[str], room_floors: dict[str, float]
) -> float | None:
    """A roof's sloped area, from the first of: the floor under it, its length
    along the eave and its slope length, or the floor areas of its rooms (when
    all of them have one). The floor is over the cosine of the pitch."""
    floor = data.get("floor_m2")
    if floor is None:
        floor = _area(data, "length_m", "slope_m")
        if floor is not None:
            return floor
        if rooms and all(area in room_floors for area in rooms):
            floor = sum(room_floors[area] for area in rooms)
        else:
            return None
    return float(floor) / math.cos(math.radians(tilt))


def roof_areas(data: dict) -> list[str]:
    """A roof's rooms; one saved before roofs could be shared has ``area_id``."""
    if data.get("area_ids"):
        return list(data["area_ids"])
    return [data["area_id"]] if data.get("area_id") else []


def grid_face(data: dict, house: dict) -> str:
    """The face (N, E, S or W) of the house's grid a wall or roof looks towards.

    A part given a face keeps it; one given its own bearing takes the face
    nearest that bearing, once the house's rotation is taken off.
    """
    if data.get("facing") is None:
        return data.get("face", "S")
    rotation = float(house.get("rotation") or 0.0)
    turned = (float(data["facing"]) - rotation) % 360.0
    return ("N", "E", "S", "W")[round(turned / 90.0) % 4]


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
        house: The integration's own settings (``rotation``, ``shade_below``,
            and ``below_grade_m``, the depth a below-ground room's walls go
            below grade when the room does not give its own).
        raws: Its sub-entries.

    Returns:
        The elements by id, and a note for each sub-entry that was skipped.
    """
    elements: dict[str, Element] = {}
    problems: list[str] = []
    rooms: set[str] = set()
    room_floors = {
        raw.data.get("area_id"): float(raw.data["floor_m2"])
        for raw in raws
        if raw.kind == ROOM and raw.data.get("floor_m2") is not None
    }
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
            below = bool(d.get("below_ground", False))
            depth = _optional(d.get("below_grade_m"))
            default_depth = _optional(house.get("below_grade_m"))
            from_house = below and depth is None and default_depth is not None
            elements[raw.id] = Element(
                raw.id,
                ROOM,
                raw.title,
                area,
                floor_m2=floor,
                height_m=height,
                volume_m3=volume,
                below_ground=below,
                below_grade_m=default_depth if from_house else depth,
                below_grade_default=from_house,
                beside=_others(d.get("beside"), area),
                above=_others(d.get("above"), area),
                width_m=_optional(d.get("width_m")),
                depth_m=_optional(d.get("depth_m")),
                x_m=_optional(d.get("x_m")),
                y_m=_optional(d.get("y_m")),
                level_m=_optional(d.get("level_m")),
            )
        elif raw.kind == REGISTER:
            elements[raw.id] = Element(
                raw.id,
                REGISTER,
                raw.title,
                d.get("area_id"),
                climate=d.get("climate"),
                fan=d.get("fan") or None,
                free_area_in2=_optional(d.get("free_area_in2")),
                flow_cfm=_optional(d.get("flow_cfm")),
                duct=tuple(d.get("duct") or ()),
                upstream=d.get("upstream") or None,
                at_x_m=_optional(d.get("at_x_m")),
                at_y_m=_optional(d.get("at_y_m")),
                at_z_m=_optional(d.get("at_z_m")),
            )
        elif raw.kind == WALL:
            elements[raw.id] = Element(
                raw.id,
                WALL,
                raw.title,
                d.get("area_id"),
                plane=_plane(d, house, 90.0),
                size_m2=_area(d, "length_m", "height_m"),
                r_value_si=_optional(d.get("r_value_si")),
                length_m=_optional(d.get("length_m")),
                height_m=_optional(d.get("height_m")),
                face=grid_face(d, house),
            )
        elif raw.kind == ROOF:
            areas = roof_areas(d)
            elements[raw.id] = Element(
                raw.id,
                ROOF,
                raw.title,
                areas[0] if areas else None,
                area_ids=tuple(areas),
                plane=_plane(d, house, float(d.get("pitch", 45.0))),
                size_m2=_roof_area(d, float(d.get("pitch", 45.0)), areas, room_floors),
                r_value_si=_optional(d.get("r_value_si")),
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
        area = d.get("area_id")
        if area not in host.area_ids:  # unset, or no longer one of the roof's
            area = host.area_id
        elements[raw.id] = Element(
            raw.id,
            WINDOW,
            raw.title,
            area,
            plane=host.plane,
            size_m2=glass,
            host=host.id,
            transmittance=float(d.get("transmittance", TRANSMITTANCE)),
            blind=d.get("blind") or None,
            blind_closed=float(d.get("blind_closed", BLIND_CLOSED)),
            glazing=d.get("glazing") or None,
            frame=d.get("frame") or None,
            glass_width_m=_optional(d.get("width_m")),
            glass_height_m=_optional(d.get("height_m")),
        )
        if glass:
            elements[host.id] = replace(
                elements[host.id], glass_m2=elements[host.id].glass_m2 + glass
            )
    for raw in raws:
        if raw.kind == DOOR:
            _add_door(elements, problems, raw)
    return elements, problems


def _add_door(elements: dict[str, Element], problems: list[str], raw: Raw) -> None:
    """A door, in the outside or internal wall it names, whose area it adds to."""
    d = raw.data
    host = elements.get(d.get("host", ""))
    if host is None or host.kind not in (WALL, INTERNAL_WALL):
        problems.append(f"{raw.title}: the wall it is in was removed")
        return
    size = _area(d, "width_m", "height_m")
    elements[raw.id] = Element(
        raw.id,
        DOOR,
        raw.title,
        host.area_id,
        plane=host.plane,
        size_m2=size,
        host=host.id,
        other_area_id=host.other_area_id,
        sensor=d.get("sensor") or None,
        width_m=_optional(d.get("width_m")),
        height_m=_optional(d.get("height_m")),
    )
    if size:
        elements[host.id] = replace(
            elements[host.id], door_m2=elements[host.id].door_m2 + size
        )


def doors_in(elements: dict[str, Element], area_id: str | None) -> list[Element]:
    """A room's doors: in its outside walls, and in internal walls on either side."""
    if area_id is None:
        return []
    return [
        e
        for e in elements.values()
        if e.kind == DOOR and area_id in (e.area_id, e.other_area_id)
    ]


def windows_in(elements: dict[str, Element], area_id: str | None) -> list[Element]:
    """The windows of a room."""
    return [e for e in elements.values() if e.kind == WINDOW and e.area_id == area_id]


# The version of the room summary other integrations read; raise it when a key
# changes meaning or goes away (adding keys does not need it).
def _others(areas, own: str | None) -> tuple[str, ...]:
    """A room's list of areas, without itself or repeats."""
    return tuple(dict.fromkeys(a for a in areas or () if a and a != own))


BESIDE, ABOVE, BELOW = "beside", "above", "below"


def neighbours(elements: dict[str, Element]) -> dict[str, list[dict]]:
    """Each area's neighbours, from both sides.

    A room's ``beside`` and ``above`` lists, and internal walls, each make a
    link that both rooms get: a room listing another above it is below that
    one. A link is entered once, from either room; an internal wall's area
    is kept.

    Returns:
        By area id, ``{"area_id", "position", "area_m2"}`` for each
        neighbour, where ``position`` (``beside``, ``above`` or ``below``)
        is where the neighbour is.
    """
    links: dict[tuple[str, str], dict] = {}

    def link(area: str | None, other: str | None, position: str, area_m2=None):
        if not area or not other or area == other:
            return
        flipped = {ABOVE: BELOW, BELOW: ABOVE}.get(position, position)
        for here, there, where in ((area, other, position), (other, area, flipped)):
            item = links.setdefault(
                (here, there),
                {"area_id": there, "position": where, "area_m2": None},
            )
            if area_m2 is not None:
                item["area_m2"] = area_m2

    for e in elements.values():
        if e.kind == ROOM:
            for other in e.beside:
                link(e.area_id, other, BESIDE)
            for other in e.above:
                link(e.area_id, other, ABOVE)
        elif e.kind == INTERNAL_WALL:
            link(e.area_id, e.other_area_id, BESIDE, e.size_m2)
    out: dict[str, list[dict]] = {}
    for (area, _), item in sorted(links.items()):
        out.setdefault(area, []).append(item)
    return out


SUMMARY_VERSION = 1  # new keys may be added; a reader ignores what it does not know


def _plane_summary(element: Element) -> dict:
    plane = element.plane
    return {
        "title": element.title,
        "azimuth": round(plane.azimuth, 2),
        "tilt": round(plane.tilt, 2),
        "shade_below": plane.shade_below,
    }


def _door_summary(door: Element, host: Element, other: str | None) -> dict:
    """A door as one of its rooms lists it."""
    return {
        "title": door.title,
        "in": host.kind,
        "wall": host.title,
        "other_area_id": other,
        "azimuth": None if door.plane is None else round(door.plane.azimuth, 2),
        "width_m": door.width_m,
        "height_m": door.height_m,
        "area_m2": door.size_m2,
        "sensor": door.sensor,
    }


def _empty_room(area_id: str, temperature: str | None) -> dict:
    return {
        "area_id": area_id,
        "title": None,
        "floor_m2": None,
        "height_m": None,
        "volume_m3": None,
        "below_grade_m": None,
        "below_grade_default": False,
        "width_m": None,
        "depth_m": None,
        "below_ground": False,
        "temperature_entity": temperature,
        "windows": [],
        "doors": [],
        "walls": [],
        "roofs": [],
        "internal_walls": [],
        "registers": [],
        "neighbours": [],
    }


def rooms_summary(
    elements: dict[str, Element], temperature: dict[str, str | None] | None = None
) -> dict[str, dict]:
    """Each room's parts as plain data, by area id, for other integrations.

    Every area with a part is a room, with or without a room part. Planes are
    compass azimuths and tilts in degrees; areas in m2. An internal wall is
    listed in the rooms on both sides, and a shared roof in each of its rooms
    (with all its rooms in ``area_ids``, and its whole area). ``neighbours``
    lists the areas beside, above and below each room (see ``neighbours``).
    A room's ``width_m`` and ``depth_m`` are its footprint (east to west and
    south to north in the house's grid); ``below_grade_default`` says its
    ``below_grade_m`` is the house's default. A wall gives its ``face`` in
    the house's grid, and its ``length_m`` and ``height_m`` when typed.
    A door is listed in its room, and a door in an internal wall in the rooms
    on both sides, each with the other room as ``other_area_id`` (``None`` for
    a door to outside); outside and internal walls give their doors' area as
    ``door_m2``.

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
        if e.kind == ROOF:
            for area_id in e.area_ids:
                room(area_id)["roofs"].append(
                    {
                        **_plane_summary(e),
                        "area_m2": e.size_m2,
                        "glass_m2": e.glass_m2,
                        "r_value_si": e.r_value_si,
                        "area_ids": list(e.area_ids),
                    }
                )
            continue
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
                below_grade_m=e.below_grade_m,
                below_grade_default=e.below_grade_default,
                width_m=e.width_m,
                depth_m=e.depth_m,
            )
        elif e.kind == WALL:
            here["walls"].append(
                {
                    **_plane_summary(e),
                    "face": e.face,
                    "length_m": e.length_m,
                    "height_m": e.height_m,
                    "area_m2": e.size_m2,
                    "glass_m2": e.glass_m2,
                    "door_m2": e.door_m2,
                    "r_value_si": e.r_value_si,
                }
            )
        elif e.kind == DOOR:
            sides = [(e.area_id, e.other_area_id)]
            if e.other_area_id:  # in an internal wall: both rooms list it
                sides.append((e.other_area_id, e.area_id))
            for this, other in sides:
                side = room(this)
                if side is not None:
                    side["doors"].append(_door_summary(e, elements[e.host], other))
        elif e.kind == WINDOW:
            here["windows"].append(
                {
                    **_plane_summary(e),
                    "in": elements[e.host].kind,
                    "glass_m2": e.size_m2,
                    "transmittance": e.transmittance,
                    "glazing": e.glazing,
                    "frame": e.frame,
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
                        {
                            "title": e.title,
                            "other_area_id": other,
                            "area_m2": e.size_m2,
                            "door_m2": e.door_m2,
                        }
                    )
        elif e.kind == REGISTER:
            here["registers"].append(
                {
                    "title": e.title,
                    "climate": e.climate,
                    "fan": e.fan,
                    "free_area_in2": e.free_area_in2,
                    "flow_cfm": e.flow_cfm,
                    "duct": [dict(seg) for seg in e.duct],
                    "upstream": e.upstream,
                }
            )
    # an area without parts (a garage, say) is a neighbour, but not a room
    for area_id, items in neighbours(elements).items():
        if area_id in rooms:
            rooms[area_id]["neighbours"] = items
    return rooms
