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
drawn on their faces, each as long as its length (walls on a face follow each
other), and any stretch of face no wall covers is dashed. Its windows and doors
are centred on their walls in a row (window sills at ``SILL``, doors from the
floor), and its registers are dots. An internal wall is drawn on the face its
room shares with the room on the other side, from either room, found from the
two rooms' positions, and a door in one is drawn on it; without the positions
the wall is listed under the drawing instead.
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
from .ducts import R_IMPERIAL_TO_SI
from .geometry import FACES, FEET_INCHES, FOOT, format_size
from .model import Element

COS30 = math.sqrt(3) / 2
SIN30 = 0.5
DEFAULT_CEILING = 2.4  # m, where no ceiling height is given
DEFAULT_GLASS = (0.9, 1.2)  # m wide and high, where a window has no size
DEFAULT_DOOR = (0.9, 2.03)  # m wide and high (a 36 by 80 inch door), where untyped
TOUCH = 0.3  # m: two rooms closer than this across a face share a wall
SILL = 0.9  # m above the floor, for a window's sill
DEFAULT_OUTLET = 0.1  # m above the floor, where a register has no height
CORNER_EPS = 0.02  # m: a register this close to a room's vertical corner sits on it
CORNER_OFFSET = 0.15  # m: how far along the wall it is set off from that corner
# m: how far an untyped register is moved from the middle (east, then north). The
# two differ so the moved spot is on no corner line in any of the four views.
DEFAULT_NUDGE = (0.15, 0.3)
GAP = 1.0  # m between rooms placed without a position
FLOOR_GAP = 3.0  # m between floors' groups of rooms placed without a position
EXPLODE_GAP = 2.5  # m added between floors when they are drawn apart
# The three bands along each axis, from the low edge (south or west) to the high
# one (north or east): a room is put against the edge its outside walls are on.
BANDS = ("low", "mid", "high")
# Rooms whose floors are less than this above a floor's lowest room share that
# floor: a split level's half flight (3 1/2 ft, a little under half a wall)
# stays with its floor, while a full storey above starts a new one.
LEVEL_STEP = 3.5 * FOOT
SHEET_HEIGHT = 900  # px for the drawing, before the captions
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
DEFAULT_NOTE = "* Manual J default R-value: none typed."
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


class Label(NamedTuple):
    """A short text drawn centred on a point, in its layer (``dims``, ``rvalues``)."""

    point: Point
    text: str
    layer: str = "dims"


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
    labels: list[Label] = field(default_factory=list)
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
    box: Box,
    face: str,
    windows: list[Element],
    doors: list[Element],
    start: float = 0.0,
    end: float | None = None,
) -> list[Poly]:
    """The doors and windows of one wall, centred on its stretch of the face
    (``start`` to ``end`` metres along it; the whole face by default) in a row:
    doors first, from the floor, then windows, sills at ``SILL``."""
    sizes = [(*_door_size(d), True) for d in doors]
    sizes += [
        (
            w.glass_width_m or DEFAULT_GLASS[0],
            w.glass_height_m or DEFAULT_GLASS[1],
            False,
        )
        for w in windows
    ]
    span = (_span(box, face) if end is None else end) - start
    total = sum(width for width, _, _ in sizes)
    scale = min(1.0, 0.9 * span / total) if total else 1.0
    along = start + (span - total * scale) / 2
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
    # untyped: near the middle, nudged in both x and y, so it clears the vertical
    # edges of the corners in every view (the same plan spot in every rotation)
    x = box.width / 2 if reg.at_x_m is None else reg.at_x_m
    y = box.depth / 2 if reg.at_y_m is None else reg.at_y_m
    if reg.at_x_m is None and box.width / 2 + DEFAULT_NUDGE[0] < box.width:
        x += DEFAULT_NUDGE[0]
    if reg.at_y_m is None and box.depth / 2 + DEFAULT_NUDGE[1] < box.depth:
        y += DEFAULT_NUDGE[1]
    z = DEFAULT_OUTLET if reg.at_z_m is None else reg.at_z_m
    # a register at a room's corner is set off along the wall,
    # clear of the corner's edge
    on_x_edge = x < CORNER_EPS or box.width - x < CORNER_EPS
    on_y_edge = y < CORNER_EPS or box.depth - y < CORNER_EPS
    if on_x_edge and on_y_edge:
        x += CORNER_OFFSET if x < box.width / 2 else -CORNER_OFFSET
    return box.x + x, box.y + y, box.z + z


class Parts(NamedTuple):
    """The parts the drawings need, grouped."""

    walls: dict[str, list[Element]]  # by room
    windows: dict[str, list[Element]]  # by wall
    doors: dict[str, list[Element]]  # by outside wall
    inside_doors: dict[str, list[Element]]  # by room, on either side of the door
    outlets: dict[str, list[Element]]  # by room
    internal: dict[str, list[Element]]  # by room, on either side of the wall


def _sides(e: Element) -> set[str]:
    """The rooms on either side of an internal wall (or a door in one)."""
    return {area for area in (e.area_id, e.other_area_id) if area}


def _parts(elements: dict[str, Element]) -> Parts:
    """The walls of each room, the windows and doors of each outside wall, the
    internal walls and the doors in them (for both rooms either side), and the
    outlets of each room."""
    parts = Parts({}, {}, {}, {}, {}, {})
    for e in elements.values():
        if e.kind == WALL:
            parts.walls.setdefault(e.area_id or "", []).append(e)
        elif e.kind == WINDOW and e.host in elements:
            if elements[e.host].kind == WALL:  # a skylight is not drawn
                parts.windows.setdefault(e.host, []).append(e)
        elif e.kind == DOOR and e.host in elements:
            if elements[e.host].kind == INTERNAL_WALL:
                for area in _sides(e):
                    parts.inside_doors.setdefault(area, []).append(e)
            else:
                parts.doors.setdefault(e.host, []).append(e)
        elif e.kind == INTERNAL_WALL:
            for area in _sides(e):
                parts.internal.setdefault(area, []).append(e)
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


def _wall_stretches(
    walls: list[Element], span: float
) -> list[tuple[Element, float, float]]:
    """Each outside wall's stretch of its face, from the face's west or south end.

    Walls on one face follow each other in the order given, each as long as its
    length (up to the face's span). A wall with no length runs the whole face.
    """
    out: list[tuple[Element, float, float]] = []
    at = 0.0
    for wall in walls:
        if wall.length_m:
            end = min(at + wall.length_m, span)
            out.append((wall, at, end))
            at = end
        else:
            out.append((wall, 0.0, span))
    return out


def _gaps(covered: list[tuple[float, float]], span: float) -> list[tuple[float, float]]:
    """The stretches of a face (0 to ``span``) that no wall covers."""
    gaps: list[tuple[float, float]] = []
    at = 0.0
    for start, end in sorted(covered):
        if start - at > 1e-6:
            gaps.append((at, start))
        at = max(at, end)
    if span - at > 1e-6:
        gaps.append((at, span))
    return gaps


def _r_text(r_si: float | None, unit: str, default_si: float | None = None) -> str:
    """An R-value as the house's unit has it: ``R-20`` in feet and inches, ``RSI 3.52``
    in metres. A part with none typed shows the default, starred (see ``DEFAULT_NOTE``),
    or nothing when there is no default either."""
    value, star = r_si, ""
    if value is None:
        if default_si is None:
            return ""
        value, star = default_si, "*"
    if unit == FEET_INCHES:
        r = value / R_IMPERIAL_TO_SI
        return (f"R-{r:.0f}" if r >= 10 else f"R-{r:.1f}") + star
    return f"RSI {value:.2f}{star}"


def _room_dims(box: Box, unit: str) -> list[Label]:
    """A room's width, depth and height, on its near edges."""
    return [
        Label(
            _on_face(box, "S", box.width / 2, 0.0),
            f"{format_size(box.width, unit)} wide",
            "dims",
        ),
        Label(
            _on_face(box, "E", box.depth / 2, 0.0),
            f"{format_size(box.depth, unit)} deep",
            "dims",
        ),
        Label(
            (box.x + box.width, box.y, box.z + box.height / 2),
            f"{format_size(box.height, unit)} high",
            "dims",
        ),
    ]


def _wall_labels(
    box: Box,
    face: str,
    wall: Element,
    start: float,
    end: float,
    unit: str,
    defaults: dict[str, float],
) -> list[Label]:
    """A wall's drawn length and height (upper part), and its R-value (lower part)."""
    height = wall.height_m or box.height
    middle = (start + end) / 2
    return [
        Label(
            _on_face(box, face, middle, height * 0.75),
            f"{format_size(end - start, unit)} x {format_size(height, unit)}",
            "dims",
        ),
        Label(
            _on_face(box, face, middle, height * 0.25),
            _r_text(wall.r_value_si, unit, defaults.get("wall_r")),
            "rvalues",
        ),
    ]


def _opening_label(e: Element, unit: str) -> str:
    """A door's or window's size, and a window's glazing and frame. A size not
    typed is the drawing's assumed one, and says so."""
    if e.kind == DOOR:
        width, height = _door_size(e)
        typed = e.width_m is not None and e.height_m is not None
        text = f"door {format_size(width, unit)} x {format_size(height, unit)}"
    else:
        width = e.glass_width_m or DEFAULT_GLASS[0]
        height = e.glass_height_m or DEFAULT_GLASS[1]
        typed = e.glass_width_m is not None and e.glass_height_m is not None
        text = f"window {format_size(width, unit)} x {format_size(height, unit)}"
        extras = [
            part
            for part in (
                e.glazing and f"{e.glazing} glazed",
                e.frame and f"{e.frame} frame",
            )
            if part
        ]
        if extras:
            text += ", " + ", ".join(extras)
    return text if typed else f"{text} (size assumed)"


def _opening_labels(
    openings: list[Poly],
    elements: list[Element],
    unit: str,
    defaults: dict[str, float],
) -> list[Label]:
    """A label at the middle of each door or window (``openings`` in the order
    ``_openings`` drew them, with the elements they came from)."""
    labels = []
    for poly, e in zip(openings, elements, strict=True):
        middle = [sum(p[i] for p in poly.points) / len(poly.points) for i in range(3)]
        labels.append(Label(tuple(middle), _opening_label(e, unit), "dims"))
        if e.kind == DOOR:  # an outside door's R-value, in its lower quarter
            heights = [p[2] for p in poly.points]
            low = min(heights) + (max(heights) - min(heights)) / 4
            at = (middle[0], middle[1], low)
            labels.append(
                Label(
                    at, _r_text(e.r_value_si, unit, defaults.get("door_r")), "rvalues"
                )
            )
    return labels


def _add_room(
    scene: Scene,
    box: Box,
    rotation: float,
    parts: Parts,
    colours: dict[str, str],
    inside: list[tuple[Element, str, float, float]] | None = None,
    unit: str = "m",
    labelled: bool = False,
    defaults: dict[str, float] | None = None,
) -> None:
    """Draw one room's floor, walls, windows, doors and outlets (far faces first).

    ``inside`` is the room's internal walls and the doors in them, each with the
    face and the stretch of it to draw on (see ``_shared_face``). A stretch of a
    face that no wall covers is dashed.
    """
    defaults = defaults or {}
    # an upper floor is see-through, so the room below shows through it
    floor_opacity = 0.7 if box.z > 0 else 1.0
    scene.polygons.append(Poly(_floor(box), FLOOR_FILL, FLOOR_LINE, floor_opacity))
    scene.labels.extend(_room_dims(box, unit))
    by_face: dict[str, list[Element]] = {face: [] for face in FACE_ORDER}
    for wall in parts.walls.get(box.area, []):
        by_face[_face_of(wall, rotation)].append(wall)
    near = near_faces(scene.view)
    for face in face_order(scene.view):
        opacity = 0.6 if face in near else 0.9
        span = _span(box, face)
        stretches = _wall_stretches(by_face[face], span)
        shared = [(item, s, e) for item, on, s, e in inside or () if on == face]
        covered = [(s, e) for _, s, e in stretches] + [(s, e) for _, s, e in shared]
        for start, end in _gaps(covered, span):
            outline = _quad(box, face, start, end, 0.0, box.height)
            scene.polygons.append(Poly(outline, "none", MISSING_LINE, 1.0, True))
        for wall, start, end in stretches:
            outline = _quad(box, face, start, end, 0.0, box.height)
            scene.polygons.append(Poly(outline, WALL_FILL, WALL_LINE, opacity))
            wins = parts.windows.get(wall.id, [])
            drs = parts.doors.get(wall.id, [])
            openings = _openings(box, face, wins, drs, start, end)
            scene.polygons.extend(openings)
            if labelled:
                scene.labels.extend(
                    _opening_labels(openings, [*drs, *wins], unit, defaults)
                )
            scene.labels.extend(
                _wall_labels(box, face, wall, start, end, unit, defaults)
            )
        for item, start, end in shared:  # the walls first, so the doors sit on them
            if item.kind == INTERNAL_WALL:
                outline = _quad(box, face, start, end, 0.0, box.height)
                scene.polygons.append(Poly(outline, WALL_FILL, WALL_LINE, opacity))
        for item, start, end in shared:
            if item.kind == DOOR:
                scene.polygons.append(_inside_door(box, item, face, start, end))
    for reg in parts.outlets.get(box.area, []):
        scene.dots.append(Dot(_outlet(box, reg), colours[reg.id], reg.title, "runs"))


def _inside_parts(
    elements: dict[str, Element],
    parts: Parts,
    area_id: str,
    boxes: dict[str, Box],
) -> tuple[list[tuple[Element, str, float, float]], list[str]]:
    """A room's internal walls, and the doors in them, each on the face it shares
    with the room on the other side (``boxes``: where each room is placed), and a
    note for each that cannot be placed."""
    here = boxes.get(area_id)
    placed, notes = [], []
    # a wall is drawn from both rooms; a door only from its own room (its area)
    items = [
        *parts.internal.get(area_id, []),
        *(d for d in parts.inside_doors.get(area_id, []) if d.area_id == area_id),
    ]
    for item in items:
        # the room on the other side: the wall's, or the door's (its wall's)
        other_id = item.other_area_id if item.area_id == area_id else item.area_id
        there = boxes.get(other_id or "")
        found = _shared_face(here, there) if here and there else None
        if found is None:
            why = (
                "the two rooms do not touch"
                if here and there
                else "one of its rooms has no size yet"
            )
            notes.append(f"{item.title}: not drawn; {why}")
            continue
        placed.append((item, *found))
    return placed, notes


def _floor_lines(
    rooms: list[Element], floors: dict[str, int] | None = None
) -> list[list[Element]]:
    """Rooms grouped by floor, lowest first. With ``floors`` (each area's floor
    level), a room's floor is its area's; rooms with none come last. Otherwise a
    room within ``LEVEL_STEP`` of a floor's lowest one shares that floor (as in
    ``floor_lifts``)."""
    if floors is not None:
        by_floor: dict[int | None, list[Element]] = {}
        for room in rooms:
            by_floor.setdefault(floors.get(room.area_id or ""), []).append(room)
        known = sorted(k for k in by_floor if k is not None)
        return [by_floor[k] for k in known] + (
            [by_floor[None]] if None in by_floor else []
        )
    lines: list[list[Element]] = []
    for room in sorted(rooms, key=lambda r: r.level_m or 0.0):
        z = room.level_m or 0.0
        if lines and z - (lines[-1][0].level_m or 0.0) < LEVEL_STEP:
            lines[-1].append(room)
        else:
            lines.append([room])
    return lines


def _outside_faces(
    elements: dict[str, Element], rotation: float
) -> dict[str, set[str]]:
    """The house faces each area has outside walls on."""
    faces: dict[str, set[str]] = {}
    for e in elements.values():
        if e.kind == WALL and e.area_id:
            faces.setdefault(e.area_id, set()).add(_face_of(e, rotation))
    return faces


def _band(faces: set[str], low: str, high: str) -> str:
    """Where a room sits along one axis: against the low edge if its outside walls
    are on that edge only, against the high edge likewise, else in the middle."""
    if high in faces and low not in faces:
        return "high"
    if low in faces and high not in faces:
        return "low"
    return "mid"


def _starts(sizes: dict[str, float], start: float) -> dict[str, float]:
    """Where each non-empty band starts, one ``GAP`` after the band before it."""
    starts: dict[str, float] = {}
    at = start
    for band in BANDS:
        if sizes.get(band):
            starts[band] = at
            at += sizes[band] + GAP
    return starts


def _grid_line(
    line: list[Element],
    faces: dict[str, set[str]],
    x0: float,
    y0: float,
    unit: str,
) -> tuple[list[Box], list[str], float]:
    """One floor's rooms with no position typed, on a 3 by 3 grid of the house's
    edges. A room goes in the column its outside walls put it against (west, east,
    or the middle) and the row likewise (south, north, or the middle). Each row and
    column is as wide or deep as its biggest cell, and a room sits against the edge
    it is on. Returns the boxes, the notes and the depth the grid takes."""
    notes: list[str] = []
    cells: dict[tuple[str, str], list[Box]] = {}
    for room in line:
        box = _box(room, 0.0, 0.0, room.level_m or 0.0, unit)
        if box is None:
            notes.append(f"{room.title}: no size yet, so it is not drawn")
            continue
        here = faces.get(room.area_id or "", set())
        key = (_band(here, "S", "N"), _band(here, "W", "E"))
        cells.setdefault(key, []).append(box)

    def cell_width(key: tuple[str, str]) -> float:
        members = cells.get(key, [])
        return sum(b.width for b in members) + GAP * max(len(members) - 1, 0)

    def cell_depth(key: tuple[str, str]) -> float:
        return max((b.depth for b in cells.get(key, [])), default=0.0)

    col_w = {c: max(cell_width((r, c)) for r in BANDS) for c in BANDS}
    row_d = {r: max(cell_depth((r, c)) for c in BANDS) for r in BANDS}
    col_x = _starts({c: w for c, w in col_w.items() if w}, x0)
    row_y = _starts({r: d for r, d in row_d.items() if d}, y0)
    boxes: list[Box] = []
    for (r, c), members in cells.items():
        x = col_x[c] + _start_of(c, col_w[c], cell_width((r, c)))
        for box in members:
            y = row_y[r] + _start_of(r, row_d[r], box.depth)
            boxes.append(replace(box, x=x, y=y))
            x += box.width + GAP
    depth = max(row_y[r] + row_d[r] for r in row_y) - y0 if row_y else 0.0
    return boxes, notes, depth


def _start_of(band: str, space: float, used: float) -> float:
    """Where something ``used`` metres long sits in a band ``space`` long: against
    the low edge, centred, or against the high edge."""
    return {"low": 0.0, "mid": (space - used) / 2, "high": space - used}[band]


# the way out of a room through each of its faces, along the house grid
OUTWARD = {"N": (0.0, 1.0), "S": (0.0, -1.0), "E": (1.0, 0.0), "W": (-1.0, 0.0)}


def _touching(p: Box, face: str, n: Box) -> Box:
    """``n`` set against ``p``'s ``face``, its low edge level with p's."""
    x, y = {
        "E": (p.x + p.width, p.y),
        "W": (p.x - n.width, p.y),
        "N": (p.x, p.y + p.depth),
        "S": (p.x, p.y - n.depth),
    }[face]
    return replace(n, x=x, y=y)


def _overlaps(a: Box, b: Box) -> bool:
    """Whether two boxes take up the same space (touching is not overlapping)."""
    return (
        min(a.x + a.width, b.x + b.width) - max(a.x, b.x) > TOUCH
        and min(a.y + a.depth, b.y + b.depth) - max(a.y, b.y) > TOUCH
        and a.z < b.z + b.height
        and b.z < a.z + a.height
    )


def _against(p: Box, n: Box, others: list[Box], walled: set[str]) -> Box | None:
    """``n`` set against one of ``p``'s faces: the one that points most towards
    where ``n`` was placed, faces with an outside wall last. None when every
    such spot would overlap another room."""
    dx = (n.x + n.width / 2) - (p.x + p.width / 2)
    dy = (n.y + n.depth / 2) - (p.y + p.depth / 2)
    order = sorted(OUTWARD, key=lambda f: -(OUTWARD[f][0] * dx + OUTWARD[f][1] * dy))
    order.sort(key=lambda f: f in walled)  # stable: the walled faces go last
    for face in order:
        spot = _touching(p, face, n)
        if not any(_overlaps(spot, o) for o in others):
            return spot
    return None


def _snap_to_walls(
    boxes: dict[str, Box],
    typed: set[str],
    walls: list[tuple[str, str]],
    faces: dict[str, set[str]],
) -> dict[str, str]:
    """Move each room with no typed position against the room it shares an
    internal wall with, on the same floor, and so on from there.

    ``boxes`` holds every room's box (changed in place); ``typed`` are the rooms
    whose positions are given, and ``walls`` each internal wall's two rooms. A
    group of linked rooms with no typed room keeps the one it was grid-placed at
    as its start. Returns each moved room's ``room it was put against``.
    """
    links: dict[str, set[str]] = {}
    for a, b in walls:
        if a != b and a in boxes and b in boxes:
            links.setdefault(a, set()).add(b)
            links.setdefault(b, set()).add(a)
    fixed = set(typed)
    seen: set[str] = set()
    for start in sorted(boxes):
        if start in seen:
            continue
        group: set[str] = set()
        todo = [start]
        while todo:
            area = todo.pop()
            if area not in group:
                group.add(area)
                todo.extend(links.get(area, ()))
        seen |= group
        if not group & fixed:
            fixed.add(min(group))
    snapped: dict[str, str] = {}
    queue = sorted(fixed)
    while queue:
        p_area = queue.pop(0)
        p = boxes[p_area]
        for n_area in sorted(links.get(p_area, ())):
            if n_area in fixed or abs(boxes[n_area].z - p.z) >= LEVEL_STEP:
                continue
            others = [b for k, b in boxes.items() if k != n_area]
            spot = _against(p, boxes[n_area], others, faces.get(p_area, set()))
            if spot is None:
                continue
            boxes[n_area] = spot
            snapped[n_area] = p_area
            fixed.add(n_area)
            queue.append(n_area)
    return snapped


def _place(
    elements: dict[str, Element],
    unit: str,
    floors: dict[str, int] | None = None,
    rotation: float = 0.0,
    view: int = 0,
) -> tuple[list[Box], list[str]]:
    """Each room's box at its position. Rooms without one go after them, each
    floor's rooms in a grid placed by their outside walls, one floor group above
    the one before, ``FLOOR_GAP`` apart. Upper floors go up the page from the
    view's side, whichever way the view turns."""
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
    faces = _outside_faces(elements, rotation)
    typed = {b.area for b in boxes}
    grid_placed: set[str] = set()
    # the way along the house's y axis that goes up the page in this view
    _, screen_dy = project((0.0, 1.0, 0.0), view)
    up = 1.0 if screen_dy < 0 else -1.0
    stacked = 0.0  # how far the floor groups have gone so far
    for line in _floor_lines(loose, floors):
        line_boxes, line_notes, depth = _grid_line(line, faces, edge, 0.0, unit)
        if depth:
            # the first floor sits at 0; each one after goes up the page from it
            start = stacked if up > 0 else -(stacked + depth)
            line_boxes = [replace(b, y=b.y + start) for b in line_boxes]
            stacked += depth + FLOOR_GAP
        boxes.extend(line_boxes)
        grid_placed |= {b.area for b in line_boxes}
        notes.extend(line_notes)
    by_area = {b.area: b for b in boxes}
    walls = [
        (e.area_id or "", e.other_area_id or "")
        for e in elements.values()
        if e.kind == INTERNAL_WALL
    ]
    snapped = _snap_to_walls(by_area, typed, walls, faces)
    titles = {e.area_id: e.title for e in elements.values() if e.kind == ROOM}
    for area in sorted(grid_placed):
        if area in snapped:
            other = titles.get(snapped[area], snapped[area])
            notes.append(
                f"{titles.get(area, area)}: no position typed, so it is placed "
                f"against {other} by their shared wall"
            )
        else:
            notes.append(
                f"{titles.get(area, area)}: no position typed, so it is placed "
                "from its walls"
            )
    boxes = [by_area[b.area] for b in boxes]
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
    unit: str = "m",
    defaults: dict[str, float] | None = None,
) -> None:
    """Each roof as a slope on top of its rooms: the ``roofs`` layer, its R-value
    on the slope in the ``rvalues`` layer.

    A roof rises from its eave, on its face's side of the room, at its pitch.
    It spans the room, or half of it when the room also has a roof on the
    opposite face (a gable: the two meet at the ridge, and the gable ends are
    drawn as walls, except where the room beyond is under the same roof).
    Roofs on adjacent faces (a hip) are each drawn as if the
    other weren't there. The ceiling is taken as flat under it.
    """
    defaults = defaults or {}
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
            middle = [
                sum(p[i] for p in slope.points) / len(slope.points) for i in range(3)
            ]
            scene.labels.append(
                Label(
                    tuple(middle),
                    _r_text(roof.r_value_si, unit, defaults.get("roof_r")),
                    "rvalues",
                )
            )
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


def render(scene: Scene, width: int = 900) -> str:
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
    for label in scene.labels:
        if not label.text:
            continue
        x, y = at(label.point).split(",")
        layers.setdefault(label.layer, []).append(
            f'<text x="{x}" y="{y}" fill="#222222" font-size="11" font-weight="600" '
            'text-anchor="middle" stroke="#ffffff" stroke-width="3" '
            f'paint-order="stroke">{escape(label.text, quote=False)}</text>'
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
        # the head: a triangle back from the tip;
        # the crossbar: across the shaft's middle
        px, py = -dy, dx
        back_x, back_y = tip_x - 7 * dx, tip_y - 7 * dy
        head = " ".join(
            f"{x:.1f},{y:.1f}"
            for x, y in (
                (tip_x, tip_y),
                (back_x + 4 * px, back_y + 4 * py),
                (back_x - 4 * px, back_y - 4 * py),
            )
        )
        out.append(
            '<g data-layer="north">'
            f'<line x1="{base_x:.1f}" y1="{base_y:.1f}" x2="{tip_x:.1f}" '
            f'y2="{tip_y:.1f}" stroke="#333333" stroke-width="2"/>'
            f'<polygon points="{head}" fill="#333333"/>'
            f'<line x1="{cx - 5 * px:.1f}" y1="{cy - 5 * py:.1f}" '
            f'x2="{cx + 5 * px:.1f}" y2="{cy + 5 * py:.1f}" '
            'stroke="#333333" stroke-width="2"/>'
            f'<text x="{cx + 19 * dx:.1f}" y="{cy + 19 * dy + 4:.1f}" '
            'fill="#333333" font-weight="bold" text-anchor="middle">N</text></g>'
        )
    # one text per note, its wrapped lines as tspans; each note also keeps its whole
    # text in data-note, so the page can show the captions as its own text
    notes = list(scene.notes)
    if any(label.text.endswith("*") for label in scene.labels):
        notes.append(DEFAULT_NOTE)
    wrapped = [textwrap.wrap(note, CAPTION_CHARS) or [""] for note in notes]
    total = draw_h + LINE * sum(len(parts) for parts in wrapped) + 10
    captions = []
    y = draw_h + 14
    for note, parts in zip(notes, wrapped, strict=True):
        spans = "".join(
            f'<tspan x="{MARGIN}" dy="{LINE if i else 0}">'
            f"{escape(part, quote=False)}</tspan>"
            for i, part in enumerate(parts)
        )
        captions.append(
            f'<text x="{MARGIN}" y="{y:.0f}" fill="#444444" '
            f'data-note="{escape(note, quote=True)}">{spans}</text>'
        )
        y += LINE * len(parts)
    background = f'<rect width="{width}" height="{total:.0f}" fill="#ffffff"/>'
    body = background + "".join(out)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{total:.0f}" viewBox="0 0 {width} {total:.0f}" '
        f'data-drawing-height="{draw_h:.0f}" '
        f'font-family="sans-serif" font-size="12">{body}'
        f'<g data-layer="notes">{"".join(captions)}</g></svg>'
    )


def room_svg(
    elements: dict[str, Element],
    house: dict,
    area_id: str,
    view: int = 0,
    defaults: dict[str, float] | None = None,
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
    placed, _ = _place(elements, unit, None, rotation, view)
    where = {b.area: b for b in placed}
    inside, door_notes = _inside_parts(elements, parts, area_id, where)
    _add_room(
        scene,
        box,
        rotation,
        parts,
        _colours(elements),
        inside,
        unit,
        labelled=True,
        defaults=defaults,
    )
    _add_roofs(scene, [box], elements, rotation, unit, defaults)
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
    floors: dict[str, int] | None = None,
    defaults: dict[str, float] | None = None,
) -> str:
    """The house from its rooms at their positions, with the heating runs on it.

    ``exploded`` draws the floors apart, each lifted ``EXPLODE_GAP`` more than
    the one below, so an upper floor doesn't hide the one under it. The runs
    are drawn to the lifted floors but measured on the real ones. ``view``
    turns the view by quarter turns (see ``VIEWS``). ``floors`` gives each
    area's floor level, which sorts the rooms without a position into lines.
    """
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    boxes, notes = _place(elements, unit, floors, rotation, view)
    lifts = floor_lifts(boxes) if exploded else []
    drawn = [replace(b, z=b.z + _lift_of(b.z, lifts)) for b in boxes]
    colours = _colours(elements)
    parts = _parts(elements)
    where = {b.area: b for b in boxes}
    scene = Scene(north=_north(rotation, view), view=view % 4)
    for box in sorted(drawn, key=lambda b: _depth_key(b, view)):
        inside, door_notes = _inside_parts(elements, parts, box.area, where)
        _add_room(scene, box, rotation, parts, colours, inside, unit, defaults=defaults)
        notes.extend(door_notes)
    _add_runs(scene, boxes, elements, house, colours, lifts)
    _add_roofs(scene, drawn, elements, rotation, unit, defaults)
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
    return render(scene)
