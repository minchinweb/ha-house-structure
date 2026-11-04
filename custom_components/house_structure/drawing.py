# Copyright (c) 2026 MinchinWeb
"""Isometric drawings: each room, the house from its rooms, and the heating runs.

Standard library only, so the tests run without Home Assistant.

The frame is the house grid: x runs east and y north along the house's own
faces (its N face is the wall at the top of each room's footprint), z is height,
and the origin is the house's south-west corner on the ground. The drawing looks
down from the south-west, so east runs right and away, and north left and away;
``view`` turns that by quarter turns, to look from the other corners.
Compass north is drawn as an arrow, from the house rotation.

A room is a box of its footprint and ceiling height. Its outside walls are
drawn on their faces (a face with no wall part is dashed), its windows and
doors are centred on their walls in a row (window sills at ``SILL``, doors from
the floor), and its registers are dots. A door in an internal wall is drawn on
the face its room shares with the room on the other side, found from the two
rooms' positions; without them it is listed under the drawing instead.
The house view places each room at its position and floor level, and draws each
register's run from the plenum: straight across at the plenum's height, then up
or down to the outlet. The runs are schematic (they do not follow the joists or
the walls), so the length shown is the drawn run, listed beside the duct's own
stated length as a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from html import escape
import itertools
import math
import textwrap
from typing import NamedTuple

from .constants import DOOR, INTERNAL_WALL, REGISTER, ROOF, ROOM, WALL, WINDOW
from .geometry import FACES, FOOT, format_size
from .model import Element

COS30 = math.sqrt(3) / 2
SIN30 = 0.5
DEFAULT_CEILING = 2.4  # m, where no ceiling height is given
DEFAULT_GLASS = (0.9, 1.2)  # m wide and high, where a window has no size
DEFAULT_DOOR = (0.9, 2.03)  # m wide and high (a 36 by 80 inch door), where untyped
TOUCH = 0.3  # m: two rooms closer than this across a face share a wall
SILL = 0.9  # m above the floor, for a window's sill
DEFAULT_OUTLET = 0.1  # m above the floor, where a register has no height
GAP = 1.0  # m between rooms drawn in a row (no position typed)
EXPLODE_GAP = 2.5  # m added between floors when they are drawn apart
# Rooms whose floors are less than this above a floor's lowest room share that
# floor: a split level's half flight (3 1/2 ft, a little under half a wall)
# stays with its floor, while a full storey above starts a new one.
LEVEL_STEP = 3.5 * FOOT
SHEET_HEIGHT = 520  # px for the drawing, before the captions
MARGIN = 16  # px
LINE = 16  # px per caption line
CAPTION_CHARS = 56  # characters per caption line, to fit the drawing's width
RUN_COLOURS = (
    "#e0562b",
    "#2e8b57",
    "#7b3fb0",
    "#c98f00",
    "#1f77b4",
    "#c2185b",
    "#00838f",
    "#6d4c41",
)
FLOOR_FILL, FLOOR_LINE = "#f3efe6", "#8a8170"
WALL_FILL, WALL_LINE = "#e2d3ae", "#7a6a46"
WINDOW_FILL, WINDOW_LINE = "#9fd3f0", "#3b7bb0"
DOOR_FILL, DOOR_LINE = "#a8744a", "#5c3b1e"
ROOF_FILL, ROOF_LINE = "#9c7b6b", "#4e342e"
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
# the way into a room from each face, along the house grid
INWARD = {"S": (0.0, 1.0), "N": (0.0, -1.0), "W": (1.0, 0.0), "E": (-1.0, 0.0)}
MISSING_LINE = "#b0a58c"
FACE_ORDER = ("N", "E", "S", "W")  # far faces first, so the near ones overlay them
NEAR_FACES = ("S", "W")
# The corner the drawing looks from, by quarter turns of the view (``view``):
# 0 is the south-west, then each turn goes a corner clockwise round the house.
VIEWS = ("south-west", "north-west", "north-east", "south-east")
_NEAR_BY_VIEW = (("S", "W"), ("N", "W"), ("N", "E"), ("S", "E"))

Point = tuple[float, float, float]  # metres in the house grid


class Poly(NamedTuple):
    """A flat shape: its corners, fill, outline and layer."""

    points: list[Point]
    fill: str
    stroke: str
    opacity: float = 1.0
    dashed: bool = False
    layer: str = "rooms"


class Run(NamedTuple):
    """A polyline (a duct run)."""

    points: list[Point]
    colour: str
    width: float = 2.6


class Dot(NamedTuple):
    """A point with a label (an outlet, the plenum), and its layer."""

    point: Point
    colour: str
    label: str = ""
    layer: str = "runs"


@dataclass(frozen=True)
class Box:
    """A room's footprint and height, at its position in the house grid."""

    title: str
    area: str
    x: float
    y: float
    z: float
    width: float
    depth: float
    height: float
    notes: tuple[str, ...] = ()


class Anchor(NamedTuple):
    """A point an overlay can draw at, named by ``data-`` attributes.

    Not drawn: ``render`` puts anchors in a hidden group, in the drawing's own
    pixel space, so a page can draw arrows and labels at them without knowing
    the projection.
    """

    point: Point
    attrs: dict[str, str]


@dataclass
class Scene:
    """What to draw, and the caption under it.

    The walls, floors, windows and doors are the ``rooms`` layer; the duct
    runs, the plenum and the outlets (``Dot.layer``) are the ``runs`` layer.
    """

    polygons: list[Poly] = field(default_factory=list)
    lines: list[Run] = field(default_factory=list)
    dots: list[Dot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    north: tuple[float, float] | None = None  # the direction of true north, on the page
    anchors: list[Anchor] = field(default_factory=list)
    view: int = 0  # quarter turns of the view (see ``VIEWS``)


def _turn(x: float, y: float, view: int) -> tuple[float, float]:
    """A point of the house grid turned so the corner seen from is the south-west."""
    return ((x, y), (-y, x), (-x, -y), (y, -x))[view % 4]


def project(point: Point, view: int = 0) -> tuple[float, float]:
    """Where a point of the house grid sits on the page (y grows downwards).

    ``view`` is the quarter turns of the view (see ``VIEWS``).
    """
    x, y = _turn(point[0], point[1], view)
    z = point[2]
    return (x - y) * COS30, -(x + y) * SIN30 - z


def near_faces(view: int = 0) -> tuple[str, str]:
    """The two faces of a room that look towards the viewer."""
    return _NEAR_BY_VIEW[view % 4]


def face_order(view: int = 0) -> tuple[str, ...]:
    """The faces far first, so the near ones are drawn over them."""
    near = near_faces(view)
    return (*(f for f in FACE_ORDER if f not in near), *near)


def _distance(a: Point, b: Point) -> float:
    return math.dist(a, b)


def _turn_gap(a: float, b: float) -> float:
    gap = abs(a - b) % 360.0
    return min(gap, 360.0 - gap)


def _footprint(room: Element) -> tuple[float, float, list[str]] | None:
    """A room's width and depth in metres: as typed, or worked out."""
    width, depth, floor = room.width_m, room.depth_m, room.floor_m2
    if width and depth:
        return width, depth, []
    if floor and width:
        return width, floor / width, ["depth from its floor area"]
    if floor and depth:
        return floor / depth, depth, ["width from its floor area"]
    if floor:
        side = math.sqrt(floor)
        return side, side, ["drawn square: no width or depth typed"]
    return None


def _box(room: Element, x: float, y: float, z: float, unit: str) -> Box | None:
    """A room's box at a position, or None when it has no size at all."""
    found = _footprint(room)
    if found is None:
        return None
    width, depth, notes = found
    height = room.height_m
    if height is None:
        height = DEFAULT_CEILING
        notes.append(f"ceiling height assumed {format_size(height, unit)}")
    size = (
        f"{format_size(width, unit)} by {format_size(depth, unit)}, "
        f"ceiling {format_size(height, unit)}"
    )
    return Box(
        room.title,
        room.area_id or "",
        x,
        y,
        z,
        width,
        depth,
        height,
        (f"{room.title}: {size}", *(f"{room.title}: {note}" for note in notes)),
    )


def _on_face(box: Box, face: str, along: float, z: float) -> Point:
    """A point on a room's face, ``along`` metres from the face's west or south end."""
    x, y = {
        "S": (along, 0.0),
        "N": (along, box.depth),
        "W": (0.0, along),
        "E": (box.width, along),
    }[face]
    return box.x + x, box.y + y, box.z + z


def _quad(box: Box, face: str, a: float, b: float, z0: float, z1: float) -> list[Point]:
    return [
        _on_face(box, face, a, z0),
        _on_face(box, face, b, z0),
        _on_face(box, face, b, z1),
        _on_face(box, face, a, z1),
    ]


def _floor(box: Box) -> list[Point]:
    return [
        (box.x, box.y, box.z),
        (box.x + box.width, box.y, box.z),
        (box.x + box.width, box.y + box.depth, box.z),
        (box.x, box.y + box.depth, box.z),
    ]


def _face_of(wall: Element, rotation: float) -> str:
    """The house face a wall is on (the nearest, for a wall turned off the grid)."""
    turned = wall.plane.azimuth - rotation
    return min(FACES, key=lambda face: _turn_gap(turned, FACES[face]))


def _span(box: Box, face: str) -> float:
    return box.width if face in ("N", "S") else box.depth


def _door_size(door: Element) -> tuple[float, float]:
    return door.width_m or DEFAULT_DOOR[0], door.height_m or DEFAULT_DOOR[1]


def _openings(
    box: Box, face: str, windows: list[Element], doors: list[Element]
) -> list[Poly]:
    """The doors and windows of one wall, centred on it in a row: doors first,
    from the floor, then windows, sills at ``SILL``."""
    sizes = [(*_door_size(d), True) for d in doors]
    sizes += [
        (
            w.glass_width_m or DEFAULT_GLASS[0],
            w.glass_height_m or DEFAULT_GLASS[1],
            False,
        )
        for w in windows
    ]
    span = _span(box, face)
    total = sum(width for width, _, _ in sizes)
    scale = min(1.0, 0.9 * span / total) if total else 1.0
    along = (span - total * scale) / 2
    out = []
    for width, height, is_door in sizes:
        width *= scale
        if is_door:
            z0, z1 = 0.0, min(height, box.height - 0.05)
            fill, line = DOOR_FILL, DOOR_LINE
        else:
            z0 = max(0.1, min(SILL, box.height - height - 0.1))
            z1 = min(z0 + height, box.height - 0.05)
            fill, line = WINDOW_FILL, WINDOW_LINE
        quad = _quad(box, face, along, along + width, z0, z1)
        out.append(Poly(quad, fill, line, 0.9))
        along += width
    return out


def _shared_face(a: Box, b: Box) -> tuple[str, float, float] | None:
    """The face of room ``a`` that room ``b`` is on the other side of, and the
    stretch of it they share (metres along the face), or None if they do not
    touch. The rooms must overlap in height too."""
    if a.z >= b.z + b.height or b.z >= a.z + a.height:
        return None
    across = {
        "S": (abs(a.y - (b.y + b.depth)), a.x, b.x, a.width, b.width),
        "N": (abs(a.y + a.depth - b.y), a.x, b.x, a.width, b.width),
        "W": (abs(a.x - (b.x + b.width)), a.y, b.y, a.depth, b.depth),
        "E": (abs(a.x + a.width - b.x), a.y, b.y, a.depth, b.depth),
    }
    for face in FACE_ORDER:
        gap, a0, b0, a_len, b_len = across[face]
        start, end = max(a0, b0), min(a0 + a_len, b0 + b_len)
        if gap < TOUCH and end - start > 0.3:
            return face, start - a0, end - a0
    return None


def _inside_door(box: Box, door: Element, face: str, start: float, end: float) -> Poly:
    """A door in an internal wall, centred on the stretch the two rooms share."""
    width, height = _door_size(door)
    width = min(width, 0.9 * (end - start))
    middle = (start + end) / 2
    top = min(height, box.height - 0.05)
    quad = _quad(box, face, middle - width / 2, middle + width / 2, 0.0, top)
    return Poly(quad, DOOR_FILL, DOOR_LINE, 0.9)


def _outlet(box: Box, reg: Element) -> Point:
    """Where a register's outlet is on the plan: centred and at the floor if untyped."""
    x = box.width / 2 if reg.at_x_m is None else reg.at_x_m
    y = box.depth / 2 if reg.at_y_m is None else reg.at_y_m
    z = DEFAULT_OUTLET if reg.at_z_m is None else reg.at_z_m
    return box.x + x, box.y + y, box.z + z


class Parts(NamedTuple):
    """The parts the drawings need, grouped."""

    walls: dict[str, list[Element]]  # by room
    windows: dict[str, list[Element]]  # by wall
    doors: dict[str, list[Element]]  # by outside wall
    inside_doors: dict[str, list[Element]]  # by room (its internal wall's room)
    outlets: dict[str, list[Element]]  # by room


def _parts(elements: dict[str, Element]) -> Parts:
    """The walls of each room, the windows and doors of each outside wall, the
    doors in each room's internal walls, and the outlets of each room."""
    parts = Parts({}, {}, {}, {}, {})
    for e in elements.values():
        if e.kind == WALL:
            parts.walls.setdefault(e.area_id or "", []).append(e)
        elif e.kind == WINDOW and e.host in elements:
            if elements[e.host].kind == WALL:  # a skylight is not drawn
                parts.windows.setdefault(e.host, []).append(e)
        elif e.kind == DOOR and e.host in elements:
            if elements[e.host].kind == INTERNAL_WALL:
                parts.inside_doors.setdefault(e.area_id or "", []).append(e)
            else:
                parts.doors.setdefault(e.host, []).append(e)
        elif e.kind == REGISTER:
            parts.outlets.setdefault(e.area_id or "", []).append(e)
    return parts


def _colours(elements: dict[str, Element]) -> dict[str, str]:
    """A colour for each register's outlet and run, the same in every drawing."""
    registers = sorted(
        (e for e in elements.values() if e.kind == REGISTER), key=lambda e: e.id
    )
    return {
        reg.id: RUN_COLOURS[i % len(RUN_COLOURS)] for i, reg in enumerate(registers)
    }


def _add_room(
    scene: Scene,
    box: Box,
    rotation: float,
    parts: Parts,
    colours: dict[str, str],
    inside: list[tuple[Element, str, float, float]] | None = None,
) -> None:
    """Draw one room's floor, walls, windows, doors and outlets (far faces first).

    ``inside`` is the room's doors in internal walls, each with the face and
    the stretch of it to draw on (see ``_shared_face``).
    """
    # an upper floor is see-through, so the room below shows through it
    floor_opacity = 0.7 if box.z > 0 else 1.0
    scene.polygons.append(Poly(_floor(box), FLOOR_FILL, FLOOR_LINE, floor_opacity))
    by_face: dict[str, list[Element]] = {face: [] for face in FACE_ORDER}
    for wall in parts.walls.get(box.area, []):
        by_face[_face_of(wall, rotation)].append(wall)
    near = near_faces(scene.view)
    for face in face_order(scene.view):
        opacity = 0.6 if face in near else 0.9
        if not by_face[face]:
            outline = _quad(box, face, 0.0, _span(box, face), 0.0, box.height)
            scene.polygons.append(Poly(outline, "none", MISSING_LINE, 1.0, True))
        for wall in by_face[face]:
            outline = _quad(box, face, 0.0, _span(box, face), 0.0, box.height)
            scene.polygons.append(Poly(outline, WALL_FILL, WALL_LINE, opacity))
            scene.polygons.extend(
                _openings(
                    box,
                    face,
                    parts.windows.get(wall.id, []),
                    parts.doors.get(wall.id, []),
                )
            )
        for door, on, start, end in inside or ():
            if on == face:
                scene.polygons.append(_inside_door(box, door, face, start, end))
    for reg in parts.outlets.get(box.area, []):
        scene.dots.append(Dot(_outlet(box, reg), colours[reg.id], reg.title, "runs"))


def _placed_box(room: Element, unit: str) -> Box | None:
    """A room's box at its typed position, or None without one."""
    if room.x_m is None or room.y_m is None:
        return None
    return _box(room, room.x_m, room.y_m, room.level_m or 0.0, unit)


def _inside_doors(
    elements: dict[str, Element], parts: Parts, area_id: str, unit: str
) -> tuple[list[tuple[Element, str, float, float]], list[str]]:
    """A room's doors in internal walls, each on the face it shares with the
    room on the other side, and a note for each that cannot be placed."""
    rooms = {e.area_id: e for e in elements.values() if e.kind == ROOM}
    here = _placed_box(rooms[area_id], unit) if area_id in rooms else None
    placed, notes = [], []
    for door in parts.inside_doors.get(area_id, []):
        other = rooms.get(door.other_area_id)
        there = _placed_box(other, unit) if other is not None else None
        found = _shared_face(here, there) if here and there else None
        if found is None:
            why = (
                "the two rooms do not touch at their typed positions"
                if here and there
                else "type both rooms' positions to place it"
            )
            notes.append(f"{door.title}: not drawn; {why}")
            continue
        placed.append((door, *found))
    return placed, notes


def _place(elements: dict[str, Element], unit: str) -> tuple[list[Box], list[str]]:
    """Each room's box at its position; rooms without one go in a row after them."""
    boxes: list[Box] = []
    notes: list[str] = []
    loose: list[Element] = []
    for room in (e for e in elements.values() if e.kind == ROOM):
        if room.x_m is None or room.y_m is None:
            loose.append(room)
            continue
        box = _box(room, room.x_m, room.y_m, room.level_m or 0.0, unit)
        if box is None:
            notes.append(f"{room.title}: no size yet, so it is not drawn")
        else:
            boxes.append(box)
    edge = max((b.x + b.width for b in boxes), default=-GAP) + GAP
    for room in loose:
        box = _box(room, edge, 0.0, 0.0, unit)
        if box is None:
            notes.append(f"{room.title}: no size yet, so it is not drawn")
            continue
        boxes.append(box)
        notes.append(f"{room.title}: no position typed, so it is drawn in a row")
        edge += box.width + GAP
    for box in boxes:
        notes.extend(box.notes)
    return boxes, notes


def floor_lifts(
    boxes: list[Box], gap: float = EXPLODE_GAP
) -> list[tuple[float, float]]:
    """How far to lift each floor to draw the floors apart.

    Rooms whose floor heights are within ``LEVEL_STEP`` of the floor below's
    lowest share it (a split-level step stays on its floor). The lowest floor
    stays put; each one above goes up ``gap`` more than the one below it.

    Returns:
        ``(level, lift)`` for each floor, lowest first: anything at or above
        ``level`` (and below the next) goes up by ``lift``.
    """
    lifts: list[tuple[float, float]] = []
    for z in sorted({round(box.z, 3) for box in boxes}):
        if lifts and z - lifts[-1][0] < LEVEL_STEP:
            continue
        lifts.append((z, gap * len(lifts)))
    return lifts


def _lift_of(z: float, lifts: list[tuple[float, float]]) -> float:
    """The lift for something at height ``z``: its floor's (none below the lowest)."""
    out = 0.0
    for level, lift in lifts:
        if z + 1e-6 >= level:
            out = lift
    return out


def _lifted(point: Point, lift: float) -> Point:
    return point[0], point[1], point[2] + lift


def _roof_faces(elements: dict[str, Element], rotation: float) -> dict[str, list]:
    """Each room's roofs, as ``(roof, face)``, by area."""
    out: dict[str, list] = {}
    for roof in (e for e in elements.values() if e.kind == ROOF and e.plane):
        face = _face_of(roof, rotation)
        for area in roof.area_ids:
            out.setdefault(area, []).append((roof, face))
    return out


def _add_roofs(
    scene: Scene,
    boxes: list[Box],
    elements: dict[str, Element],
    rotation: float,
) -> None:
    """Each roof as a slope on top of its rooms: the ``roofs`` layer.

    A roof rises from its eave, on its face's side of the room, at its pitch.
    It spans the room, or half of it when the room also has a roof on the
    opposite face (a gable: the two meet at the ridge, and the gable ends are
    drawn as walls, except where the room beyond is under the same roof).
    Roofs on adjacent faces (a hip) are each drawn as if the
    other weren't there. The ceiling is taken as flat under it.
    """
    faces_by_area = _roof_faces(elements, rotation)
    order = {face: i for i, face in enumerate(face_order(scene.view))}
    near = near_faces(scene.view)

    def roof_goes_on(box: Box, end: str, roof: Element) -> bool:
        """Whether the room beyond this end is under the same roof (no gable)."""
        for other in boxes:
            shared = _shared_face(box, other) if other.area != box.area else None
            if shared and shared[0] == end and other.area in roof.area_ids:
                return True
        return False

    shapes = []
    for box in boxes:
        roofs = faces_by_area.get(box.area, [])
        faces = {face for _, face in roofs}
        top = box.height
        for roof, face in roofs:
            gable = OPPOSITE[face] in faces
            across = box.depth if face in ("S", "N") else box.width
            run = across / 2 if gable else across
            rise = run * math.tan(math.radians(roof.plane.tilt))
            ix, iy = INWARD[face]
            length = _span(box, face)
            eave = [_on_face(box, face, 0.0, top), _on_face(box, face, length, top)]
            ridge = [
                (x + ix * run, y + iy * run, z + rise) for x, y, z in reversed(eave)
            ]
            slope = Poly([*eave, *ridge], ROOF_FILL, ROOF_LINE, 0.92, layer="roofs")
            key = _depth_key(box, scene.view)
            shapes.append((key, order[face], slope))
            # each gable end once: from the south or west roof of the pair
            if gable and face in ("S", "W"):
                for end in ("W", "E") if face == "S" else ("S", "N"):
                    if roof_goes_on(box, end, roof):
                        continue
                    middle = _span(box, end) / 2
                    peak = _on_face(box, end, middle, top + rise)
                    sides = [_on_face(box, end, 0.0, top), peak]
                    sides.append(_on_face(box, end, _span(box, end), top))
                    gable_end = Poly(sides, WALL_FILL, WALL_LINE, 0.9, layer="roofs")
                    # a far end faces away: behind the slopes, which hide it
                    rank = len(order) if end in near else -1
                    shapes.append((key, rank, gable_end))
    for *_, poly in sorted(shapes, key=lambda s: (s[0], s[1])):
        scene.polygons.append(poly)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> tuple[float, float]:
    """Where two spans overlap (empty when the end is not past the start)."""
    return max(a0, b0), min(a1, b1)


def _pair(a: str, b: str) -> str:
    """Two areas as one key, the same either way round."""
    return "|".join(sorted((a, b)))


def _add_anchors(
    scene: Scene,
    real: list[Box],
    drawn: list[Box],
    parts: Parts,
    rotation: float,
) -> None:
    """The points overlays draw at, worked out on the drawn (maybe lifted) rooms.

    Which rooms touch is found where they really are (``real``), so drawing
    the floors apart doesn't lose a room above another. Each anchor is:

    * ``data-room``: the room's centre, half way up;
    * ``data-between="a|b"`` (the two areas, sorted): the middle of the wall
      two rooms share, half way up the height they share; or, for a room over
      another, the middle of the floor between them (half way across the gap
      when the floors are apart);
    * ``data-outside="area|face"``: the middle of each face with an outside
      wall part, half way up;
    * ``data-register`` (its part id), with ``data-room``: each outlet.
    """
    lifted = {box.area: box for box in drawn}
    for box in drawn:
        centre = (box.x + box.width / 2, box.y + box.depth / 2, box.z + box.height / 2)
        scene.anchors.append(Anchor(centre, {"room": box.area}))
        faces = {_face_of(wall, rotation) for wall in parts.walls.get(box.area, [])}
        for face in sorted(faces):
            point = _on_face(box, face, _span(box, face) / 2, box.height / 2)
            scene.anchors.append(Anchor(point, {"outside": f"{box.area}|{face}"}))
        for reg in parts.outlets.get(box.area, []):
            scene.anchors.append(
                Anchor(_outlet(box, reg), {"register": reg.id, "room": box.area})
            )
    seen: set[str] = set()
    for a, b in itertools.combinations(real, 2):
        key = _pair(a.area, b.area)
        if a.area == b.area or key in seen:
            continue
        la = lifted[a.area]  # a side anchor follows the first room's floor
        side = _shared_face(a, b)
        if side is not None:
            face, start, end = side
            low, high = _overlap(a.z, a.z + a.height, b.z, b.z + b.height)
            point = _on_face(la, face, (start + end) / 2, (low + high) / 2 - a.z)
            scene.anchors.append(Anchor(point, {"between": key}))
            seen.add(key)
            continue
        lower, upper = (a, b) if a.z <= b.z else (b, a)
        if abs(lower.z + lower.height - upper.z) >= TOUCH:
            continue
        x0, x1 = _overlap(a.x, a.x + a.width, b.x, b.x + b.width)
        y0, y1 = _overlap(a.y, a.y + a.depth, b.y, b.y + b.depth)
        if x1 - x0 <= 0.3 or y1 - y0 <= 0.3:
            continue
        lo, up = lifted[lower.area], lifted[upper.area]
        z = (lo.z + lo.height + up.z) / 2
        scene.anchors.append(
            Anchor(((x0 + x1) / 2, (y0 + y1) / 2, z), {"between": key})
        )
        seen.add(key)


def _depth_key(box: Box, view: int = 0) -> float:
    """Draw far and low rooms first: the painter's order from the view's corner."""
    x, y = _turn(box.x + box.width / 2, box.y + box.depth / 2, view)
    return 2 * box.z - (x + y)


def _plenum(house: dict) -> Point | None:
    """The plenum's place in the house grid, if its east and north are typed."""
    x, y = house.get("plenum_x_m"), house.get("plenum_y_m")
    if x is None or y is None:
        return None
    return float(x), float(y), float(house.get("plenum_z_m") or 0.0)


def _add_runs(
    scene: Scene,
    boxes: list[Box],
    elements: dict[str, Element],
    house: dict,
    colours: dict[str, str],
    lifts: list[tuple[float, float]] | None = None,
) -> None:
    """Each register's run from the plenum, and a check of its length.

    ``boxes`` are where the rooms really are. With ``lifts`` (floors drawn
    apart), each run is drawn to its outlet on the lifted floor, but its length
    is still measured where the rooms really are.
    """
    lifts = lifts or []
    registers = [e for e in elements.values() if e.kind == REGISTER]
    plenum = _plenum(house)
    if plenum is None:
        if registers:
            scene.notes.append(
                "Type the plenum's position in the house form to draw the runs."
            )
        return
    plenum_lift = _lift_of(plenum[2], lifts)
    scene.dots.append(Dot(_lifted(plenum, plenum_lift), "#222222", "Plenum"))
    by_area = {box.area: box for box in boxes}
    for reg in sorted(registers, key=lambda e: e.title):
        box = by_area.get(reg.area_id or "")
        if box is None:
            scene.notes.append(f"{reg.title}: its room is not drawn, so no run")
            continue
        target = _outlet(box, reg)
        path = [plenum, (target[0], target[1], plenum[2]), target]
        drawn = sum(_distance(a, b) for a, b in itertools.pairwise(path)) / FOOT
        if lifts:
            path = [
                _lifted(path[0], plenum_lift),
                _lifted(path[1], plenum_lift),
                _lifted(target, _lift_of(box.z, lifts)),
            ]
        scene.lines.append(Run(path, colours[reg.id]))
        if reg.duct:
            feet = sum(seg.get("length_ft", 0.0) for seg in reg.duct)
            stated = f"duct {feet:.0f} ft" + (" (its branch)" if reg.upstream else "")
        else:
            stated = "no duct typed"
        scene.notes.append(f"{reg.title}: run {drawn:.0f} ft drawn, {stated}")


def _north(rotation: float, view: int = 0) -> tuple[float, float]:
    """True north on the page: the house's y axis turned back by its rotation."""
    turn = math.radians(rotation)
    dx, dy = project((-math.sin(turn), math.cos(turn), 0.0), view)
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def render(scene: Scene, width: int = 360) -> str:
    """The scene as an SVG, the captions under the drawing."""
    view = scene.view
    corners = [project(p, view) for poly in scene.polygons for p in poly.points]
    corners += [project(p, view) for run in scene.lines for p in run.points]
    corners += [project(dot.point, view) for dot in scene.dots]
    xs = [x for x, _ in corners] or [0.0]
    ys = [y for _, y in corners] or [0.0]
    left, top = min(xs), min(ys)
    span_x = max(max(xs) - left, 1.0)
    span_y = max(max(ys) - top, 1.0)
    scale = min(
        (width - 2 * MARGIN) / span_x,
        (SHEET_HEIGHT - 2 * MARGIN) / span_y,
    )
    draw_h = span_y * scale + 2 * MARGIN

    def at(point: Point) -> str:
        x, y = project(point, view)
        return f"{MARGIN + (x - left) * scale:.1f},{MARGIN + (y - top) * scale:.1f}"

    # the order the layers are drawn in: the roofs over the rooms and runs
    layers: dict[str, list[str]] = {"rooms": [], "runs": [], "roofs": []}
    for poly in scene.polygons:
        dash = ' stroke-dasharray="4 3"' if poly.dashed else ""
        layers.setdefault(poly.layer, []).append(
            f'<polygon points="{" ".join(at(p) for p in poly.points)}" '
            f'fill="{poly.fill}" fill-opacity="{poly.opacity}" '
            f'stroke="{poly.stroke}" stroke-width="1.2"{dash}/>'
        )
    for run in scene.lines:
        layers["runs"].append(
            f'<polyline points="{" ".join(at(p) for p in run.points)}" fill="none" '
            f'stroke="{run.colour}" stroke-width="{run.width}" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    for dot in scene.dots:
        x, y = at(dot.point).split(",")
        layers.setdefault(dot.layer, []).append(
            f'<circle cx="{x}" cy="{y}" r="4.5" fill="{dot.colour}" '
            f'stroke="#ffffff" stroke-width="1.5">'
            f"<title>{escape(dot.label, quote=False)}</title></circle>"
        )
    out = [
        f'<g data-layer="{name}">{"".join(items)}</g>'
        for name, items in layers.items()
        if items
    ]
    if scene.anchors:
        points = []
        for anchor in scene.anchors:
            x, y = at(anchor.point).split(",")
            attrs = "".join(
                f' data-{key}="{escape(value, quote=True)}"'
                for key, value in anchor.attrs.items()
            )
            points.append(f'<circle cx="{x}" cy="{y}" r="0"{attrs}/>')
        out.append(f'<g data-layer="anchors" visibility="hidden">{"".join(points)}</g>')
    if scene.north is not None:
        dx, dy = scene.north
        # centred in its corner, so the arrow and its N fit whichever way it points
        cx, cy = width - MARGIN - 20, MARGIN + 20
        base_x, base_y = cx - 11 * dx, cy - 11 * dy
        tip_x, tip_y = cx + 11 * dx, cy + 11 * dy
        out.append(
            '<g data-layer="north">'
            f'<line x1="{base_x:.1f}" y1="{base_y:.1f}" x2="{tip_x:.1f}" '
            f'y2="{tip_y:.1f}" stroke="#333333" stroke-width="2"/>'
            f'<text x="{cx + 19 * dx:.1f}" y="{cy + 19 * dy + 4:.1f}" '
            'fill="#333333" font-weight="bold" text-anchor="middle">N</text></g>'
        )
    wrapped = [
        line
        for note in scene.notes
        for line in textwrap.wrap(note, CAPTION_CHARS) or [""]
    ]
    total = draw_h + LINE * len(wrapped) + 10
    lines = [
        f'<text x="{MARGIN}" y="{draw_h + 14 + i * LINE:.0f}" fill="#444444">'
        f"{escape(line, quote=False)}</text>"
        for i, line in enumerate(wrapped)
    ]
    background = f'<rect width="{width}" height="{total:.0f}" fill="#ffffff"/>'
    body = background + "".join(out)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{total:.0f}" viewBox="0 0 {width} {total:.0f}" '
        f'data-drawing-height="{draw_h:.0f}" '
        f'font-family="sans-serif" font-size="12">{body}'
        f'<g data-layer="notes">{"".join(lines)}</g></svg>'
    )


def room_svg(
    elements: dict[str, Element], house: dict, area_id: str, view: int = 0
) -> str | None:
    """One room's isometric drawing, or None when the area has no room part.

    ``view`` turns the view by quarter turns (see ``VIEWS``).
    """
    room = next(
        (e for e in elements.values() if e.kind == ROOM and e.area_id == area_id),
        None,
    )
    if room is None:
        return None
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    scene = Scene(north=_north(rotation, view), view=view % 4)
    box = _box(room, 0.0, 0.0, 0.0, unit)
    if box is None:
        scene.notes.append(
            f"{room.title}: no size yet. Type its width and depth, or its floor area."
        )
        return render(scene)
    parts = _parts(elements)
    faces = {_face_of(w, rotation) for w in parts.walls.get(area_id, [])}
    inside, door_notes = _inside_doors(elements, parts, area_id, unit)
    _add_room(scene, box, rotation, parts, _colours(elements), inside)
    _add_roofs(scene, [box], elements, rotation)
    scene.notes.extend(box.notes)
    scene.notes.extend(door_notes)
    missing = [face for face in FACE_ORDER if face not in faces]
    if missing:
        scene.notes.append(
            "Dashed faces have no wall part yet: " + ", ".join(missing) + "."
        )
    scene.notes.append(
        f"Looking from the {VIEWS[view % 4]}. Windows and doors (brown) sit centred, "
        f"window sills at {SILL:g} m."
    )
    return render(scene)


def house_svg(
    elements: dict[str, Element],
    house: dict,
    exploded: bool = False,
    view: int = 0,
) -> str:
    """The house from its rooms at their positions, with the heating runs on it.

    ``exploded`` draws the floors apart, each lifted ``EXPLODE_GAP`` more than
    the one below, so an upper floor doesn't hide the one under it. The runs
    are drawn to the lifted floors but measured on the real ones. ``view``
    turns the view by quarter turns (see ``VIEWS``).
    """
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    boxes, notes = _place(elements, unit)
    lifts = floor_lifts(boxes) if exploded else []
    drawn = [replace(b, z=b.z + _lift_of(b.z, lifts)) for b in boxes]
    colours = _colours(elements)
    parts = _parts(elements)
    scene = Scene(north=_north(rotation, view), view=view % 4)
    for box in sorted(drawn, key=lambda b: _depth_key(b, view)):
        inside, door_notes = _inside_doors(elements, parts, box.area, unit)
        _add_room(scene, box, rotation, parts, colours, inside)
        notes.extend(door_notes)
    _add_runs(scene, boxes, elements, house, colours, lifts)
    _add_roofs(scene, drawn, elements, rotation)
    _add_anchors(scene, boxes, drawn, parts, rotation)
    if not boxes:
        notes.append("No rooms are drawn yet.")
    key = f"Looking from the {VIEWS[view % 4]}."
    if len(lifts) > 1:
        key += (
            f" Floors drawn apart: each is lifted {format_size(EXPLODE_GAP, unit)} "
            "more than the one below, so heights between floors are not to scale."
        )
    scene.notes = [key, *notes, *scene.notes]
    return render(scene, width=420)
