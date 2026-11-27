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
other, in the stretches of it with no room against them). A stretch of face
with a typed internal wall is solid; an open (no-wall)
neighbour is a dotted outline; a beside neighbour with no internal wall part yet
is dash-dotted; any remaining stretch (no wall and no neighbour) is dashed.
Its windows and doors are centred on their walls in a row (window sills at
``SILL``, doors from the floor), and its registers are dots. An internal wall
is drawn on the face its room shares with the room on the other side, from
either room, found from the two rooms' positions, and a door in one is drawn on
it; without the positions the wall is listed under the drawing instead.
The house view places each room at its position and floor level (a room with
no position is fitted to the others: see ``layout.py``), and draws each
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
from typing import Any, NamedTuple

from . import layout
from .constants import DOOR, INTERNAL_WALL, REGISTER, ROOF, ROOM, STAIRS, WALL, WINDOW
from .ducts import R_IMPERIAL_TO_SI
from .geometry import (
    FACE_NAMES,
    FACES,
    FEET_INCHES,
    FOOT,
    INCH,
    OPPOSITE,
    format_size,
)
from .model import ABOVE, BELOW, BESIDE, Element, neighbours

COS30 = math.sqrt(3) / 2
SIN30 = 0.5
DEFAULT_CEILING = 2.4  # m, where no ceiling height is given
DEFAULT_GLASS = (0.9, 1.2)  # m wide and high, where a window has no size
# m wide and high, where a door has no size: 28 by 80 inches for a door between
# rooms, 32 by 80 inches for a door to outside
INSIDE_DOOR = (28 * 0.0254, 80 * 0.0254)
OUTSIDE_DOOR = (32 * 0.0254, 80 * 0.0254)
TOUCH = 0.3  # m: two rooms closer than this across a face share a wall
NORTH_COLUMN = 60  # px kept clear on the right of the drawing for the north arrow
SILL = 0.9  # m above the floor, for a window's sill
DEFAULT_OUTLET = 0.1  # m above the floor, where a register has no height
CORNER_EPS = 0.02  # m: a register this close to a room's vertical corner sits on it
CORNER_OFFSET = 0.15  # m: how far along the wall it is set off from that corner
# m: how far an untyped register is moved from the middle (east, then north). The
# two differ so the moved spot is on no corner line in any of the four views.
DEFAULT_NUDGE = (0.15, 0.3)
OPENING_GAP = 0.1  # m between one door or window in a wall and the next
# A link's arrow (see ``_add_links``): how far it reaches past its room's wall, or up
# or down to a room above or below, the size of its head, and its colour
LINK_REACH = 0.8  # m
LINK_RISE = 1.0  # m
LINK_HEAD = 0.18  # m
LINK_COLOUR = "#37474f"
# the plan's connections layer (see ``_add_connections``): a line between the
# middles of the floors of each two rooms that are linked, dashed when they are
# open to each other
CONNECTION_COLOUR = "#6a1b9a"
CONNECTION_DASH = "6 4"
LARGE_TEXT = 1.6  # the text scale of a single room drawn with large text
BUILDING_GAP = 2.0  # m between the house and a detached building with no position
SLAB = 0.3  # m from a ceiling to the floor above, where no floor height is typed
# what houses are built to, by the house's unit: the rooms shaped to fit are
# a whole number of these wide and deep (inches, or centimetres)
BUILT_TO = {FEET_INCHES: 0.0254, "ft": 0.0254, "in": 0.0254, "m": 0.01}
# a wall between two rooms: studs and board both sides (4 1/2 in). Rooms are
# measured inside, so the house fits them together this far apart.
INNER_WALL = 4.5 * INCH
EXPLODE_GAP = 1.5  # m between floors on the page when they are drawn apart
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
OPENING_FILL, OPENING_LINE = "#e6dcc4", "#5c5446"  # stairs' opening on the floor above
WALL_FILL, WALL_LINE = "#e2d3ae", "#7a6a46"
# a wall between two rooms is a cooler grey-green, so it reads apart from outside walls
INSIDE_FILL, INSIDE_LINE = "#cfdcd6", "#51655c"
WINDOW_FILL, WINDOW_LINE = "#9fd3f0", "#3b7bb0"
DOOR_FILL, DOOR_LINE = "#a8744a", "#5c3b1e"
ROOF_FILL, ROOF_LINE = "#9c7b6b", "#4e342e"
# Face outlines when there is no solid wall fill: missing exterior, open
# neighbour (no wall), and implied neighbour (beside, wall not typed yet).
MISSING_LINE, MISSING_DASH = "#b0a58c", "4 3"
OPEN_LINE, OPEN_DASH = "#78909c", "1.5 3.5"
IMPLIED_LINE, IMPLIED_DASH = "#5d5346", "7 3 1.5 3"
# the way into a room from each face, along the house grid
INWARD = {"S": (0.0, 1.0), "N": (0.0, -1.0), "W": (1.0, 0.0), "E": (-1.0, 0.0)}
SIZE_NOTE = "a: Size assumed: no size typed, so the drawing uses its default size."
DEFAULT_NOTE = "b: Manual J default R-value: none typed."  # its label is marked b
# a room's width, depth or height that was not typed, but found from what was
WORKED_NOTE = (
    "c: Worked out, not typed: from the floor area or the floor heights, "
    "or shaped to fit the rooms round it."
)
# the positions layer (see ``_add_positions``): the origin, and a pin on each room
# with a typed position
ORIGIN_COLOUR, POSITION_COLOUR = "#333333", "#00796b"
FACE_ORDER = ("N", "E", "S", "W")  # far faces first, so the near ones overlay them
NEAR_FACES = ("S", "W")
# The corner the drawing looks from, by quarter turns of the view (``view``):
# 0 is the south-west, then each turn goes a corner clockwise round the house.
VIEWS = ("south-west", "north-west", "north-east", "south-east")
# From above (``top_down``), the side at the top of the page, by the same quarter
# turns: the way the view at that turn looks, squared to a side.
UP_BY_VIEW = ("north", "east", "south", "west")
TOP_WALL_WIDTH = 3.0  # px: a wall seen from above is a line, drawn this thick
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
    dasharray: str = MISSING_DASH


class Run(NamedTuple):
    """A polyline (a duct run, or a link's arrow in its own ``layer``)."""

    points: list[Point]
    colour: str
    width: float = 2.6
    layer: str = "runs"
    dasharray: str = ""


class Dot(NamedTuple):
    """A point with a label (an outlet, the plenum), and its layer."""

    point: Point
    colour: str
    label: str = ""
    layer: str = "runs"


class Label(NamedTuple):
    """A short text drawn centred on a point, in its layer (``dims``, ``rvalues``).

    ``note`` is the letter of a footnote (see ``SIZE_NOTE``, ``DEFAULT_NOTE``,
    ``WORKED_NOTE``),
    drawn small after the text.
    """

    point: Point
    text: str
    layer: str = "dims"
    note: str = ""


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
    # the holes in its floor: space with rooms all round that no room was given
    holes: tuple[tuple[float, float, float, float], ...] = ()
    # an L-shaped room's wing (or a room's two wings): each east and north of
    # the room's south-west corner, then its width and depth
    wings: tuple[tuple[float, float, float, float], ...] = ()
    # stairs that reach another floor: the area whose floor this box is on (the
    # flight is on the lower floor, so its box is that floor's), the area on the
    # upper floor, and the height of that floor, where the opening is drawn
    floor_area: str | None = None
    top_area: str | None = None
    top_z: float | None = None
    # which of ``width``, ``depth`` and ``height`` were typed (the others were
    # worked out or assumed), and whether its position was typed
    typed: frozenset[str] = frozenset({"width", "depth", "height"})
    fixed: bool = False


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
    top_down: bool = False  # drawn from straight above (see ``project``)
    text_scale: float = 1.0  # the size of the labels' text, 1 for normal
    height: int = SHEET_HEIGHT  # px the drawing may take, before the captions


def _turn(x: float, y: float, view: int) -> tuple[float, float]:
    """A point of the house grid turned so the corner seen from is the south-west."""
    return ((x, y), (-y, x), (-x, -y), (y, -x))[view % 4]


def project(point: Point, view: int = 0, top_down: bool = False) -> tuple[float, float]:
    """Where a point of the house grid sits on the page (y grows downwards).

    ``view`` is the quarter turns of the view (see ``VIEWS``). ``top_down``
    draws it from straight above, a plan: its height is lost, and the side
    ``UP_BY_VIEW`` names is at the top of the page.
    """
    x, y = _turn(point[0], point[1], view)
    if top_down:
        return x, -y
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


WING = "#wing"  # after a room's area: its wing's name among the rooms fitted
WINGS = (WING, "#wing2")  # its first wing's, and its second's
# after stairs' area: its opening's name among the rooms fitted on the floor above
MIRROR = "#up"


def _wings(room: Element) -> list[tuple[str, tuple[float, float, str, bool]]]:
    """A room's wings (an L-shaped room has one; a T or U, two), each after
    its name's ending among the rooms fitted (``WINGS``): its width, depth,
    the face of the room's main rectangle it is against, and whether it is to
    be shaped to fit (it has a floor area, but no width or depth: it is
    square until then). Empty for a room with no wing."""
    out = []
    for suffix, (width, depth, area, face) in zip(
        WINGS,
        (
            (room.wing_width_m, room.wing_depth_m, room.wing_floor_m2, room.wing_face),
            (
                room.wing2_width_m,
                room.wing2_depth_m,
                room.wing2_floor_m2,
                room.wing2_face,
            ),
        ),
        strict=True,
    ):
        if face not in FACES:
            continue
        if width and depth:
            out.append((suffix, (width, depth, face, False)))
        elif area and width:
            out.append((suffix, (width, area / width, face, False)))
        elif area and depth:
            out.append((suffix, (area / depth, depth, face, False)))
        elif area:
            out.append((suffix, (math.sqrt(area), math.sqrt(area), face, True)))
    return out


def _footprint(room: Element) -> tuple[float, float, list[str]] | None:
    """The width and depth in metres of a room (of its main rectangle, for a
    room with wings: the floor area is of that and the wings): as typed, or
    worked out."""
    width, depth, floor = room.width_m, room.depth_m, room.floor_m2
    winged = sum(wing[0] * wing[1] for _, wing in _wings(room))
    if floor and winged and floor > winged:
        floor -= winged
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


def _box(
    room: Element,
    x: float,
    y: float,
    z: float,
    unit: str,
    size: tuple[float, float] | None = None,
) -> Box | None:
    """A room's box at a position, or None when it has no size at all.

    ``size`` is the width and depth the room was given to fit its neighbours,
    for a room with neither typed (see ``_place``).
    """
    found = _footprint(room)
    if found is None:
        return None
    width, depth, notes = found
    fitted = size is not None
    if size is not None:
        width, depth = size
        notes = []
    height = room.height_m
    if height is None:
        height = DEFAULT_CEILING
        notes.append(f"ceiling height assumed {format_size(height, unit)}")
    size = (
        f"{format_size(width, unit)} by {format_size(depth, unit)}, "
        f"ceiling {format_size(height, unit)}"
    )
    if fitted:
        size += " (shaped to fit: no width or depth typed)"
    typed = set()
    if not fitted:
        typed = {n for n, v in (("width", room.width_m), ("depth", room.depth_m)) if v}
    if room.height_m is not None:
        typed.add("height")
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
        typed=frozenset(typed),
        fixed=room.x_m is not None and room.y_m is not None,
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
    """A door's width and height: typed, else the default for a door between
    rooms (it names the room on the other side) or a door to outside."""
    width, height = INSIDE_DOOR if door.other_area_id else OUTSIDE_DOOR
    return door.width_m or width, door.height_m or height


def _openings(
    box: Box,
    face: str,
    windows: list[Element],
    doors: list[Element],
    start: float = 0.0,
    end: float | None = None,
) -> list[Poly]:
    """The doors and windows of one wall, on its stretch of the face (``start``
    to ``end`` metres along it; the whole face by default): doors first, from
    the floor, then windows, sills at ``SILL``.

    One with a distance from the wall's left end (``from_left_m``: seen from
    outside, so from the west end of a south wall, the south end of an east
    wall, the east end of a north wall and the north end of a west wall) goes
    there, kept on the wall. The others go in a row, in the order given,
    centred on the longest stretch of the wall that those leave free.
    """
    items = [(*_door_size(d), True, d.from_left_m) for d in doors]
    items += [
        (
            w.glass_width_m or DEFAULT_GLASS[0],
            w.glass_height_m or DEFAULT_GLASS[1],
            False,
            w.from_left_m,
        )
        for w in windows
    ]
    end = _span(box, face) if end is None else end
    span = end - start
    left_is_start = face in ("S", "E")  # the left end, seen from outside
    spots: dict[int, tuple[float, float]] = {}  # each one's stretch of the face
    for i, (width, _, _, from_left) in enumerate(items):
        if from_left is None:
            continue
        width = min(width, 0.9 * span)
        at = min(max(from_left, 0.0), span - width)
        low = start + at if left_is_start else end - at - width
        spots[i] = (low, low + width)
    loose = [i for i in range(len(items)) if i not in spots]
    if loose:
        taken = [(a - start, b - start) for a, b in spots.values()]
        free_from, free_to = max(
            _gaps(taken, span) or [(0.0, span)], key=lambda gap: gap[1] - gap[0]
        )
        room = free_to - free_from
        total = sum(items[i][0] for i in loose)
        gaps = OPENING_GAP * (len(loose) - 1)
        scale = min(1.0, max(0.9 * room - gaps, 0.0) / total) if total else 1.0
        along = start + free_from + (room - (total * scale + gaps)) / 2
        for i in loose:
            width = items[i][0] * scale
            spots[i] = (along, along + width)
            along += width + OPENING_GAP
    out = []
    for i, (_, height, is_door, _) in enumerate(items):
        low, high = spots[i]
        if is_door:
            z0, z1 = 0.0, min(height, box.height - 0.05)
            fill, line = DOOR_FILL, DOOR_LINE
        else:
            z0 = max(0.1, min(SILL, box.height - height - 0.1))
            z1 = min(z0 + height, box.height - 0.05)
            fill, line = WINDOW_FILL, WINDOW_LINE
        out.append(Poly(_quad(box, face, low, high, z0, z1), fill, line, 0.9))
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
    walls: list[Element],
    span: float,
    taken: list[tuple[float, float]] | None = None,
) -> list[tuple[Element, float, float]]:
    """Each outside wall's stretch of its face, from the face's west or south end.

    Walls on one face follow each other in the order given. A wall with a length
    takes that much of the face (all the lengths are scaled down together if they
    overrun it); the walls with no length share what is left, equally. So a lone
    wall with no length runs the whole face, and two such walls split it.

    ``taken`` are the stretches of the face with a room against them: the
    walls go in what is left, each in the first free stretch with room for it
    (the walls fill the whole face if rooms cover all of it).
    """
    free = _gaps(list(taken or ()), span) or [(0.0, span)]
    room = sum(end - start for start, end in free)
    typed = sum(wall.length_m for wall in walls if wall.length_m)
    scale = min(1.0, room / typed) if typed else 1.0
    untyped = [wall for wall in walls if not wall.length_m]
    share = (room - typed * scale) / len(untyped) if untyped else 0.0
    out: list[tuple[Element, float, float]] = []
    which, at = 0, free[0][0]
    for wall in walls:
        length = wall.length_m * scale if wall.length_m else share
        # on to a later free stretch when this one is too short for the wall
        while free[which][1] - at < length - 1e-6 and which + 1 < len(free):
            which += 1
            at = free[which][0]
        end = min(at + length, free[which][1])
        out.append((wall, at, end))
        at = end
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
    in metres. A part with none typed shows the default (see ``_r_label``), or
    nothing when there is no default either."""
    value = r_si
    if value is None:
        if default_si is None:
            return ""
        value = default_si
    if unit == FEET_INCHES:
        r = value / R_IMPERIAL_TO_SI
        return f"R-{r:.0f}" if r >= 10 else f"R-{r:.1f}"
    return f"RSI {value:.2f}"


def _r_label(
    at: Point, r_si: float | None, unit: str, default_si: float | None, layer: str
) -> Label:
    """An R-value label; one with only the Manual J default is footnoted ``b``."""
    text = _r_text(r_si, unit, default_si)
    return Label(at, text, layer, "b" if r_si is None and text else "")


def _room_dims(box: Box, unit: str) -> list[Label]:
    """A room's width, depth and height, on its near edges: one worked out is
    footnoted ``c``, a ceiling height assumed ``a``."""

    def note(side: str) -> str:
        if side in box.typed:
            return ""
        return "a" if side == "height" and box.top_z is None else "c"

    return [
        Label(
            _on_face(box, "S", box.width / 2, 0.0),
            f"{format_size(box.width, unit)} wide",
            "dims",
            note("width"),
        ),
        Label(
            _on_face(box, "E", box.depth / 2, 0.0),
            f"{format_size(box.depth, unit)} deep",
            "dims",
            note("depth"),
        ),
        Label(
            (box.x + box.width, box.y, box.z + box.height / 2),
            f"{format_size(box.height, unit)} high",
            "dims",
            note("height"),
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
        _r_label(
            _on_face(box, face, middle, height * 0.25),
            wall.r_value_si,
            unit,
            defaults.get("wall_r"),
            "rvalues",
        ),
    ]


def _opening_label(e: Element, unit: str) -> tuple[str, bool]:
    """A door's or window's size, and a window's glazing and frame, and whether
    its size was typed (one not typed is the drawing's assumed size, footnoted)."""
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
    return text, typed


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
        text, typed = _opening_label(e, unit)
        labels.append(Label(tuple(middle), text, "dims", "" if typed else "a"))
        if e.kind == DOOR:  # an outside door's R-value, in its lower quarter
            heights = [p[2] for p in poly.points]
            low = min(heights) + (max(heights) - min(heights)) / 4
            at = (middle[0], middle[1], low)
            labels.append(
                _r_label(at, e.r_value_si, unit, defaults.get("door_r"), "rvalues")
            )
    return labels


def _outline(
    box: Box,
    face: str,
    start: float,
    end: float,
    stroke: str,
    dash: str,
) -> Poly:
    """A dashed or dotted face stretch with no wall fill."""
    return Poly(
        _quad(box, face, start, end, 0.0, box.height),
        "none",
        stroke,
        1.0,
        True,
        dasharray=dash,
    )


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
    links: list[tuple[str, float, float, str]] | None = None,
    against: list[tuple[str, float, float]] | None = None,
    wing_inside: list[tuple[Element, int, str, float, float]] | None = None,
) -> None:
    """Draw one room's floor, walls, windows, doors and outlets (far faces first).

    ``wing_inside`` is like ``inside``, for the internal walls and doors on the
    faces of a room's wings, each with its wing's number (1 for the first; see
    ``_wing_parts``).

    ``inside`` is the room's internal walls and the doors in them, each with the
    face and the stretch of it to draw on (see ``_shared_face``). ``links`` are
    same-floor neighbour stretches with no typed internal wall: each
    ``(face, start, end, kind)`` where ``kind`` is ``open`` or ``implied``. A
    typed internal wall is solid; an open neighbour is dotted; an implied
    neighbour (beside, wall not typed) is dash-dotted; any leftover stretch is
    dashed as a missing exterior. ``against`` are the stretches
    ``(face, start, end)`` with anything at all against them (a room that is
    not linked, a hallway no room was given): an outside wall goes clear of
    those too, when there is room.
    """
    defaults = defaults or {}
    # an upper floor is see-through, so the room below shows through it
    floor_opacity = 0.7 if box.z > 0 else 1.0
    scene.polygons.append(Poly(_floor(box), FLOOR_FILL, FLOOR_LINE, floor_opacity))
    scene.labels.extend(_room_dims(box, unit))
    wing_boxes = _wing_boxes(box)
    for number, (wing_box, _, wing_on) in enumerate(wing_boxes, start=1):
        scene.polygons.append(
            Poly(_floor(wing_box), FLOOR_FILL, FLOOR_LINE, floor_opacity)
        )
        # no line where it runs on into what it is against, or into a wing
        # that steps out from it
        stepped = [on for _, base, on in wing_boxes if base == number and on]
        for face in face_order(scene.view):
            if wing_on is None or face != OPPOSITE[wing_on[0]]:
                joined = [(on[1], on[2]) for on in stepped if on[0] == face]
                for start, end in _gaps(joined, _span(wing_box, face)):
                    scene.polygons.append(
                        _outline(wing_box, face, start, end, WALL_LINE, "none")
                    )
            opacity = 0.6 if face in near_faces(scene.view) else 0.9
            on_face = [
                (i, s, e)
                for i, at, on, s, e in wing_inside or ()
                if at == number and on == face
            ]
            for item, start, end in on_face:  # the walls, then the doors in them
                if item.kind != INTERNAL_WALL:
                    continue
                if item.open_link:
                    scene.polygons.append(
                        _outline(wing_box, face, start, end, OPEN_LINE, OPEN_DASH)
                    )
                else:
                    quad = _quad(wing_box, face, start, end, 0.0, wing_box.height)
                    scene.polygons.append(Poly(quad, INSIDE_FILL, INSIDE_LINE, opacity))
            for item, start, end in on_face:
                if item.kind == DOOR:
                    scene.polygons.append(
                        _inside_door(wing_box, item, face, start, end)
                    )
    by_face: dict[str, list[Element]] = {face: [] for face in FACE_ORDER}
    for wall in parts.walls.get(box.area, []):
        by_face[_face_of(wall, rotation)].append(wall)
    near = near_faces(scene.view)
    for face in face_order(scene.view):
        opacity = 0.6 if face in near else 0.9
        span = _span(box, face)
        shared = [(item, s, e) for item, on, s, e in inside or () if on == face]
        # solid walls cover the face; open typed internals are drawn dotted
        solid = [
            (s, e)
            for item, s, e in shared
            if item.kind == INTERNAL_WALL and not item.open_link
        ]
        opened = [
            (s, e)
            for item, s, e in shared
            if item.kind == INTERNAL_WALL and item.open_link
        ]
        linked = [(s, e, kind) for on, s, e, kind in links or () if on == face]
        open_links = [(s, e) for s, e, kind in linked if kind == "open"]
        implied = [(s, e) for s, e, kind in linked if kind == "implied"]
        # the room runs on into its wings: no wall there, and nothing missing
        opened = opened + [
            (on[1], on[2])
            for _, base, on in wing_boxes
            if not base and on is not None and on[0] == face
        ]
        # the outside walls go where no room is against the face
        taken = solid + opened + open_links + implied
        other = [(s, e) for on, s, e in against or () if on == face]
        typed = sum(wall.length_m or 0.0 for wall in by_face[face])
        clear = sum(e - s for s, e in _gaps(taken + other, span))
        if other and clear > 0.3 and clear >= 0.6 * typed:
            taken = taken + other
        stretches = _wall_stretches(by_face[face], span, taken)
        walled = [(s, e) for _, s, e in stretches] + solid
        neighbour = opened + open_links + implied
        for start, end in _gaps(walled + neighbour, span):
            scene.polygons.append(
                _outline(box, face, start, end, MISSING_LINE, MISSING_DASH)
            )
        for start, end in opened + open_links:
            scene.polygons.append(_outline(box, face, start, end, OPEN_LINE, OPEN_DASH))
        for start, end in implied:
            scene.polygons.append(
                _outline(box, face, start, end, IMPLIED_LINE, IMPLIED_DASH)
            )
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
        for item, start, end in shared:  # solid internals first, then their doors
            if item.kind == INTERNAL_WALL and not item.open_link:
                outline = _quad(box, face, start, end, 0.0, box.height)
                scene.polygons.append(Poly(outline, INSIDE_FILL, INSIDE_LINE, opacity))
        for item, start, end in shared:
            if item.kind == DOOR:
                scene.polygons.append(_inside_door(box, item, face, start, end))
    for reg in parts.outlets.get(box.area, []):
        scene.dots.append(Dot(_outlet(box, reg), colours[reg.id], reg.title, "runs"))


def _wing_boxes(
    box: Box,
) -> list[tuple[Box, int, tuple[str, float, float] | None]]:
    """A room's wings, each as a box of its own, with the part it is against
    (0 for the room's main rectangle; 1 for its first wing, which a second
    can step out from), and the face of that part and the stretch they share
    (None when it touches neither)."""
    out: list[tuple[Box, int, tuple[str, float, float] | None]] = []
    for dx, dy, width, depth in box.wings:
        wing = Box("", "", box.x + dx, box.y + dy, box.z, width, depth, box.height)
        on, base = _shared_face(box, wing), 0
        for number, (other, _, _) in enumerate(out, start=1):
            if on is None:
                on, base = _shared_face(other, wing), number
        out.append((wing, base if on is not None else 0, on))
    return out


def _parts_of(box: Box) -> list[Box]:
    """A room's main rectangle and its wings."""
    return [box, *(wing for wing, _, _ in _wing_boxes(box))]


def _touching(a: Box, b: Box) -> bool:
    """Whether two rooms share a wall: a room's wings are part of the room."""
    return any(
        _shared_face(p, q) is not None for p in _parts_of(a) for q in _parts_of(b)
    )


def _against(here: Box, others: list[Box]) -> list[tuple[str, float, float]]:
    """The stretches of a room's faces ``(face, start, end)`` that another
    room (``others``: the rooms on its floor, where they really are), or a
    hole in its floor (a hallway no room was given), is against."""
    spaces = [
        Box("", "", r[0], r[1], here.z, r[2] - r[0], r[3] - r[1], here.height)
        for r in here.holes
    ]
    out = []
    for there in [*others, *spaces]:
        if there.area == here.area:
            continue
        found = _shared_face(here, there)
        if found is not None:
            out.append(found)
    return out


def _meeting(here: Box, there: Box) -> tuple[int, str, float, float] | None:
    """Where a room meets another: which part of the room does (0 for its
    main rectangle, else its wing's number, 1 for the first), then the face of
    that part and the stretch of it they share. The other room's wings are
    part of it. None if they do not touch."""
    others = _parts_of(there)
    for number, part in enumerate(_parts_of(here)):
        for other in others:
            found = _shared_face(part, other)
            if found is not None:
                return (number, *found)
    return None


def _inside_items(parts: Parts, area_id: str) -> list[Element]:
    """A room's internal walls and the doors in them. A wall is drawn from
    both rooms; a door only from its own room (its area)."""
    return [
        *parts.internal.get(area_id, []),
        *(d for d in parts.inside_doors.get(area_id, []) if d.area_id == area_id),
    ]


def _wing_parts(
    parts: Parts, area_id: str, boxes: dict[str, Box]
) -> list[tuple[Element, int, str, float, float]]:
    """The internal walls, and the doors in them, that are on a room's wings:
    each with its wing's number (1 for the first), the wing's face and the
    stretch of it shared with the room on the other side (like
    ``_inside_parts``)."""
    here = boxes.get(area_id)
    if here is None or not here.wings:
        return []
    out = []
    for item in _inside_items(parts, area_id):
        other_id = item.other_area_id if item.area_id == area_id else item.area_id
        there = boxes.get(other_id or "")
        found = _meeting(here, there) if there else None
        if found is not None and found[0]:
            out.append((item, *found))
    return out


def _inside_parts(
    elements: dict[str, Element],
    parts: Parts,
    area_id: str,
    boxes: dict[str, Box],
) -> tuple[list[tuple[Element, str, float, float]], list[str]]:
    """A room's internal walls, and the doors in them, each on the face it shares
    with the room on the other side (``boxes``: where each room is placed), and a
    note for each that cannot be placed. The ones on the room's wings are left
    to ``_wing_parts``."""
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
        met = _meeting(here, there) if here and there else None
        if met is not None and met[0]:
            continue  # on one of the room's wings
        found = None if met is None else met[1:]
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


def _dashed_faces(
    box: Box,
    rotation: float,
    parts: Parts,
    inside: list,
    links: list[tuple[str, float, float, str]],
) -> list[str]:
    """The faces ``_add_room`` leaves a dashed stretch on (no wall, no neighbour)."""
    out = []
    for face in FACE_ORDER:
        span = _span(box, face)
        walls = [
            w for w in parts.walls.get(box.area, []) if _face_of(w, rotation) == face
        ]
        covered = [
            (s, e)
            for item, on, s, e in inside
            if on == face and item.kind == INTERNAL_WALL
        ]
        covered += [(s, e) for on, s, e, _ in links if on == face]
        covered += [(s, e) for _, s, e in _wall_stretches(walls, span, covered)]
        if _gaps(covered, span):
            out.append(face)
    return out


def _typed_internal_others(parts: Parts, area_id: str) -> set[str]:
    """The other rooms already covered by a typed internal wall on ``area_id``."""
    others: set[str] = set()
    for wall in parts.internal.get(area_id, []):
        other = wall.other_area_id if wall.area_id == area_id else wall.area_id
        if other:
            others.add(other)
    return others


def _link_stretches(
    elements: dict[str, Element],
    parts: Parts,
    area_id: str,
    boxes: dict[str, Box],
) -> list[tuple[str, float, float, str]]:
    """Same-floor neighbour stretches with no typed internal wall.

    Each item is ``(face, start, end, kind)`` where ``kind`` is ``open`` (no wall
    between) or ``implied`` (beside, wall not typed yet). Typed internal walls
    are left to ``_inside_parts``.
    """
    here = boxes.get(area_id)
    if here is None:
        return []
    typed = _typed_internal_others(parts, area_id)
    out: list[tuple[str, float, float, str]] = []
    for link in neighbours(elements).get(area_id, []):
        if link["position"] != BESIDE:
            continue
        other_id = link["area_id"]
        if other_id in typed:
            continue
        there = boxes.get(other_id)
        met = _meeting(here, there) if there else None
        if met is None or met[0]:  # (a wing's faces are drawn plain)
            continue
        _, face, start, end = met
        out.append((face, start, end, "open" if link.get("open") else "implied"))
    return out


def _floor_lines(
    rooms: list[Element], floors: dict[str, int] | None = None
) -> list[list[Element]]:
    """Rooms grouped by floor, lowest first. With ``floors`` (each area's floor
    level), a room's floor is its area's; a room with none goes with the floor
    at level 0 (else the lowest). Otherwise a room within ``LEVEL_STEP`` of a
    floor's lowest one shares that floor."""
    if floors is not None:
        by_floor: dict[int | None, list[Element]] = {}
        for room in rooms:
            by_floor.setdefault(floors.get(room.area_id or ""), []).append(room)
        known = sorted(k for k in by_floor if k is not None)
        if None in by_floor and known:
            home = 0 if 0 in by_floor else known[0]
            by_floor[home].extend(by_floor.pop(None))
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


def _link_faces(elements: dict[str, Element]) -> dict[tuple[str, str], str]:
    """Preferred face of the first room for seating the second, from typed walls.

    An internal wall's ``face`` is the face of its ``area_id`` that the other
    room sits on. The reverse link uses the opposite face.
    """
    out: dict[tuple[str, str], str] = {}
    for e in elements.values():
        if (
            e.kind != INTERNAL_WALL
            or e.face not in OPPOSITE
            or not e.area_id
            or not e.other_area_id
        ):
            continue
        out[(e.area_id, e.other_area_id)] = e.face
        out[(e.other_area_id, e.area_id)] = OPPOSITE[e.face]
    return out


def _floor_index(
    elements: dict[str, Element], areas: set[str], floors: dict[str, int] | None
) -> dict[str, int]:
    """Each room's floor as a number, the lowest floor 0 (see ``_floor_lines``)."""
    rooms = [e for e in elements.values() if e.kind == ROOM and e.area_id in areas]
    return {
        room.area_id or "": number
        for number, line in enumerate(_floor_lines(rooms, floors))
        for room in line
    }


def _beside_pairs(elements: dict[str, Element]) -> list[tuple[str, str]]:
    """Each same-floor link as ``(area, other)``: internal walls and beside/open."""
    walls = [
        (e.area_id or "", e.other_area_id or "")
        for e in elements.values()
        if e.kind == INTERNAL_WALL
    ]
    for area, items in neighbours(elements).items():
        walls.extend((area, n["area_id"]) for n in items if n["position"] == BESIDE)
    return walls


def _levels(
    lines: list[list[Element]], floors: dict[str, int] | None
) -> dict[str, float]:
    """Each room's floor height, by area: its own where typed.

    With ``floors`` (each area's floor level), a room with no height typed
    takes its floor's: the floor at level 0 (else the lowest with a room above
    ground) is at 0, and each floor above or below is a ceiling and ``SLAB``
    away from the one before, unless every room on it has a height typed.
    Without ``floors`` a room with no height typed is at 0.
    """
    if floors is None or not lines:
        return {r.area_id or "": r.level_m or 0.0 for line in lines for r in line}
    typed = [
        min(r.level_m for r in line)
        if all(r.level_m is not None for r in line)
        else None
        for line in lines
    ]
    heights = [max(r.height_m or DEFAULT_CEILING for r in line) for line in lines]
    anchor = next(
        (
            i
            for i, line in enumerate(lines)
            if any(floors.get(r.area_id or "") == 0 for r in line)
        ),
        None,
    )
    if anchor is None:
        anchor = next(
            (
                i
                for i, line in enumerate(lines)
                if any(not r.below_ground for r in line)
            ),
            0,
        )
    base = [0.0] * len(lines)
    if typed[anchor] is not None:
        base[anchor] = typed[anchor]
    for i in range(anchor + 1, len(lines)):
        above = base[i - 1] + heights[i - 1] + SLAB
        base[i] = above if typed[i] is None else typed[i]
    for i in range(anchor - 1, -1, -1):
        below = base[i + 1] - heights[i] - SLAB
        base[i] = below if typed[i] is None else typed[i]
    return {
        r.area_id or "": base[i] if r.level_m is None else r.level_m
        for i, line in enumerate(lines)
        for r in line
    }


def _room_walls(
    elements: dict[str, Element], rotation: float
) -> dict[str, list[tuple[str, float]]]:
    """Each area's outside walls as ``(face, length)``; 0 for no length typed."""
    out: dict[str, list[tuple[str, float]]] = {}
    for e in elements.values():
        if e.kind == WALL and e.area_id:
            out.setdefault(e.area_id, []).append(
                (_face_of(e, rotation), e.length_m or 0.0)
            )
    return out


def _detached(
    building: Any,
) -> tuple[list[str], str | None, float | None, float | None]:
    """A detached building's areas, side, gap and along, from what is passed.

    A building is a list of areas (it sits east of the house, ``BUILDING_GAP``
    away, south ends level), or a dict with ``area_ids`` and, optionally,
    ``side`` (``N``, ``E``, ``S`` or ``W``), ``gap_m`` (from the house) and
    ``along_m`` (from the house's west end for ``N`` and ``S``, its south end
    for ``E`` and ``W``): the building as ``equipment_summary`` publishes it.
    """
    if isinstance(building, dict):
        return (
            list(building.get("area_ids") or ()),
            building.get("side") or None,
            building.get("gap_m"),
            building.get("along_m"),
        )
    return list(building), None, None, None


def _beside(
    found: dict[str, layout.Rect],
    house: list[layout.Rect],
    side: str,
    gap: float,
    along: float,
) -> dict[str, layout.Rect]:
    """A building's rooms moved to the ``side`` of the house's box, ``gap`` away.

    ``along`` is measured from the west end of the box for a north or south
    side, and from the south end for an east or west one.
    """
    west = min(r[0] for r in house)
    south = min(r[1] for r in house)
    east = max(r[2] for r in house)
    north = max(r[3] for r in house)
    x0 = min(r[0] for r in found.values())
    y0 = min(r[1] for r in found.values())
    width = max(r[2] for r in found.values()) - x0
    depth = max(r[3] for r in found.values()) - y0
    if side in ("E", "W"):
        dx = (east + gap if side == "E" else west - gap - width) - x0
        dy = south + along - y0
    else:
        dx = west + along - x0
        dy = (north + gap if side == "N" else south - gap - depth) - y0
    return {k: (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy) for k, r in found.items()}


_PLACED: dict[tuple, tuple[list[Box], list[str]]] = {}  # the last few layouts
_PLACED_KEPT = 8


def _place(
    elements: dict[str, Element],
    unit: str,
    floors: dict[str, int] | None = None,
    rotation: float = 0.0,
    outline: list[tuple[float, float]] | None = None,
    buildings: list[Any] | None = None,
) -> tuple[list[Box], list[str]]:
    """Each room's box where it is in the house, and the notes on placing them.

    A room with a position typed stays there. The others are fitted together
    (see ``layout.py``): linked rooms share a wall, outside walls stay on the
    outside, a room sits over the rooms it is above, and a room with no width
    or depth typed takes the shape that fits. ``outline`` is the building
    outline in the house's grid, which the biggest floor is fitted to;
    ``buildings`` are the detached buildings, each fitted on its own and set
    beside the house: a list of areas, or a dict that also says which side of
    the house, how far from it and how far along it (see ``_detached``).

    Fitting takes a second or two, so the last few layouts are kept: the same
    house is fitted once however often it is drawn.
    """
    key = (
        unit,
        rotation,
        None if floors is None else tuple(sorted(floors.items())),
        tuple(outline) if outline else None,
        tuple(
            (tuple(sorted(areas)), side, gap, along)
            for areas, side, gap, along in map(_detached, buildings or ())
        ),
        tuple(
            repr(e)
            for e in elements.values()
            if e.kind in (ROOM, WALL, INTERNAL_WALL, ROOF)
        ),
    )
    found = _PLACED.get(key)
    if found is None:
        if len(_PLACED) >= _PLACED_KEPT:
            _PLACED.pop(next(iter(_PLACED)))
        found = _PLACED[key] = _fit_house(
            elements, unit, floors, rotation, outline, buildings
        )
    return list(found[0]), list(found[1])


def _fit_house(
    elements: dict[str, Element],
    unit: str,
    floors: dict[str, int] | None,
    rotation: float,
    outline: list[tuple[float, float]] | None,
    buildings: list[Any] | None,
) -> tuple[list[Box], list[str]]:
    """``_place``, worked out."""
    notes: list[str] = []
    rooms: list[Element] = []
    for room in (e for e in elements.values() if e.kind == ROOM):
        if _footprint(room) is None:
            notes.append(f"{room.title}: no size yet, so it is not drawn")
        else:
            rooms.append(room)
    walls = _room_walls(elements, rotation)
    eaves = {
        area: frozenset(face for _, face in roofs)
        for area, roofs in _roof_faces(elements, rotation).items()
    }
    pairs = _beside_pairs(elements)
    faces = _link_faces(elements)
    above = [
        (area, item["area_id"])
        for area, items in neighbours(elements).items()
        for item in items
        if item["position"] == ABOVE
    ]
    spots = [_detached(b) for b in buildings or ()]
    detached = [set(areas) for areas, *_ in spots]
    away = set().union(*detached) if detached else set()
    structures = [[r for r in rooms if r.area_id not in away]]
    structures += [[r for r in rooms if r.area_id in areas] for areas in detached]
    placed: dict[str, layout.Rect] = {}
    house: list[layout.Rect] = []  # the house's own rooms, once they are placed
    holes: dict[str, list[layout.Rect]] = {}  # each room's floor's holes
    levels: dict[str, float] = {}
    shaped: set[str] = set()
    loose: set[str] = set()
    # by each wing's key: its room, what it is against (the room, or the
    # room's first wing) and the face of that
    winged: dict[str, tuple[str, str, str]] = {}
    # stairs that reach another floor: each one's floor above (or below) it
    reach = {
        r.area_id or "": r.stairs_to
        for r in rooms
        if r.room_type == STAIRS and r.stairs_to and r.stairs_to != r.area_id
    }
    paired: dict[
        str, str
    ] = {}  # stairs placed with their other end on the same structure
    for number, members in enumerate(structures):
        lines = _floor_lines(members, floors)
        levels.update(_levels(lines, floors))
        # the keys that take one rectangle: each flight with its copy on its other
        # floor, and a stacked flight with the one it stacks on
        here = {r.area_id or "" for r in members}
        line_of = {r.area_id: k for k, line in enumerate(lines) for r in line}
        stacked = {
            low: high
            for low, high in above
            if low in reach
            and high in here
            and high != reach[low]
            and (floors is None or floors.get(high) == floors.get(reach[low]))
        }
        same: list[set[str]] = []
        for area, target in reach.items():
            # stairs "to" a room on their own floor reach no other floor
            if area in here and target in here and line_of[area] != line_of[target]:
                paired[area] = target
                if area in stacked:
                    _join(same, area, stacked[area])
                else:
                    copy = area + MIRROR
                    element = next(r for r in members if r.area_id == area)
                    for line in lines:
                        if any(r.area_id == target for r in line):
                            line.append(replace(element, area_id=copy))
                    _join(same, area, copy)
        mirror = [tuple(sorted(group)) for group in same]
        plan: list[layout.Floor] = []
        for line in lines:
            floor = layout.Floor(rooms=[])
            for room in line:
                area = room.area_id or ""
                width, depth, why = _footprint(room)
                wings = _wings(room)
                # what each wing is against: the room, or (a second wing on
                # the first's side) the first wing, so the room steps out twice
                first = dict(wings).get(WINGS[0])
                on: dict[str, str] = {}
                for suffix, wing in wings:
                    stepped = suffix != WINGS[0] and first and first[2] == wing[2]
                    on[suffix] = area + WINGS[0] if stepped else area
                    winged[area + suffix] = (area, on[suffix], wing[2])
                if room.x_m is not None and room.y_m is not None:
                    floor.fixed[area] = (
                        room.x_m,
                        room.y_m,
                        room.x_m + width,
                        room.y_m + depth,
                    )
                    for suffix, wing in wings:  # at the west or south end of its face
                        x0, y0, x1, y1 = floor.fixed[on[suffix]]
                        x = {"E": x1, "W": x0 - wing[0]}.get(wing[2], x0)
                        y = {"N": y1, "S": y0 - wing[1]}.get(wing[2], y0)
                        floor.fixed[area + suffix] = (x, y, x + wing[0], y + wing[1])
                        floor.wings[area + suffix] = area
                    continue
                for suffix, wing in wings:
                    floor.wings[area + suffix] = area
                    floor.rooms.append(
                        layout.Room(
                            area + suffix,
                            wing[0] * wing[1],
                            None if wing[3] else wing[:2],
                        )
                    )
                if not area.endswith(MIRROR):  # a copy takes its flight's place
                    loose.add(area)
                square = any("square" in note for note in why)
                if square:
                    shaped.add(area)
                floor.rooms.append(
                    layout.Room(
                        area,
                        width * depth,
                        None if square else (width, depth),
                        tuple(walls.get(area, ())),
                        eaves.get(area, frozenset()),
                        room.room_type in ("hallway", "stairs"),
                    )
                )
            here = {r.area_id or "" for r in line}
            floor.links = [
                (a, b, faces.get((a, b))) for a, b in pairs if a in here and b in here
            ]
            # a flight's opening on this floor is against what the flight is
            for copy in [k for k in here if k.endswith(MIRROR)]:
                flight = copy.removesuffix(MIRROR)
                floor.links += [
                    (copy, b, faces.get((a, b)))
                    for a, b in pairs
                    if a == flight and b in here
                ]
                floor.links += [
                    (a, copy, faces.get((a, b)))
                    for a, b in pairs
                    if b == flight and a in here
                ]
            # a room's wing is against the face it names (of the room, or of
            # the wing it steps out from)
            floor.links += [
                (base, key, face)
                for key, (area, base, face) in winged.items()
                if area in here
            ]
            plan.append(floor)
        found = layout.arrange(
            plan,
            above,
            outline if number == 0 else None,
            holes,
            BUILT_TO.get(unit, BUILT_TO["m"]),
            mirror,
            INNER_WALL,
        )
        if number and found and not any(floor.fixed for floor in plan):
            # a detached building with no position typed
            _, side, gap, along = spots[number - 1]
            if side is None and gap is None and along is None:
                # beside what is placed, to the east, south edges level
                east = max((r[2] for r in placed.values()), default=-BUILDING_GAP)
                south = min((r[1] for r in placed.values()), default=0.0)
                dx = east + BUILDING_GAP - min(r[0] for r in found.values())
                dy = south - min(r[1] for r in found.values())
                found = {
                    k: (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
                    for k, r in found.items()
                }
            else:
                # where it was put: the house's box when it has a side, else
                # everything placed so far
                around = house if side and house else list(placed.values())
                found = _beside(
                    found,
                    around or [(0.0, 0.0, 0.0, 0.0)],
                    side or "E",
                    BUILDING_GAP if gap is None else gap,
                    along or 0.0,
                )
        if number == 0:
            house = list(found.values())
        placed.update(found)
    boxes: list[Box] = []
    for room in rooms:
        area = room.area_id or ""
        rect = placed[area]
        size = (rect[2] - rect[0], rect[3] - rect[1]) if area in shaped else None
        box = _box(room, rect[0], rect[1], levels.get(area, 0.0), unit, size)
        if box is None:
            continue
        box = replace(box, holes=tuple(holes.get(area, ())))
        if area in paired:
            # the flight is on the lower floor, its opening on the upper one
            own, up = levels.get(area, 0.0), levels.get(paired[area], 0.0)
            if abs(up - own) > 1e-6:
                low, high = min(own, up), max(own, up)
                lower, upper = (
                    (area, paired[area]) if up > own else (paired[area], area)
                )
                box = replace(
                    box,
                    z=low,
                    height=high - low,
                    floor_area=lower,
                    top_area=upper,
                    top_z=high,
                    typed=box.typed - {"height"},  # from the floor heights
                )
        wings = [
            (placed[area + suffix], winged[area + suffix][2])
            for suffix in WINGS
            if area + suffix in placed
        ]
        if wings:
            said = " and ".join(
                f"{format_size(w[2] - w[0], unit)} by "
                f"{format_size(w[3] - w[1], unit)} on its {FACE_NAMES[face]} side"
                for w, face in wings
            )
            box = replace(
                box,
                wings=tuple(
                    (w[0] - rect[0], w[1] - rect[1], w[2] - w[0], w[3] - w[1])
                    for w, _ in wings
                ),
                notes=(
                    *box.notes,
                    f"{room.title}: L-shaped, with a wing {said}"
                    if len(wings) == 1
                    else f"{room.title}: with wings {said}",
                ),
            )
            if any(on is None for _, _, on in _wing_boxes(box)):
                notes.append(
                    f"{room.title}: a wing could not be placed against it: "
                    "check the rooms round it."
                )
        boxes.append(box)
    by_area = {b.area: b for b in boxes}
    if loose:
        notes.append(
            f"{len(loose)} room{'s have' if len(loose) > 1 else ' has'} no position "
            "typed: placed to fit the rooms linked to it and its outside walls."
        )
    floor_of = _floor_index(elements, set(by_area), floors)
    seen: set[str] = set()
    for a, b in pairs:
        if (
            a not in by_area
            or b not in by_area
            or _pair(a, b) in seen
            or not {a, b} & loose
            or floor_of.get(a) != floor_of.get(b)
        ):
            continue
        seen.add(_pair(a, b))
        if not _touching(by_area[a], by_area[b]) and not layout.linked_across(
            placed[a], placed[b], holes.get(a, []), INNER_WALL + layout.TOL
        ):
            notes.append(
                f"{by_area[a].title} and {by_area[b].title} are linked, but could "
                "not be placed against each other: check the links and outside "
                "walls of the rooms round them."
            )
    if holes:
        notes.append(
            "An empty space with rooms all round it is floor no room was given, "
            "such as a hallway: rooms linked across it are not drawn touching."
        )
    for box in boxes:
        notes.extend(box.notes)
    return boxes, notes


def _join(same: list[set[str]], *keys: str) -> None:
    """Merge the groups of keys (each a set that takes one rectangle) with ``keys``."""
    merged = set(keys)
    for group in [g for g in same if g & merged]:
        merged |= group
        same.remove(group)
    same.append(merged)


def _floor_shifts(
    boxes: list[Box], floor_of: dict[str, int], view: int
) -> dict[str, tuple[float, float]]:
    """How far to move each room (east, north) to draw the floors apart.

    The lowest floor stays put; each one above goes up the page until it is
    ``EXPLODE_GAP`` clear of the one before, whichever way the view turns, so
    a room stays straight above the rooms under it. Moving a room the same
    distance east and north (as the view sees them) moves it straight up the
    page.
    """

    def reach(box: Box) -> tuple[float, float]:
        spots = [
            _turn(box.x + dx, box.y + dy, view)
            for dx in (0.0, box.width)
            for dy in (0.0, box.depth)
        ]
        values = [(x + y) / 2 for x, y in spots]
        return min(values) + box.z, max(values) + box.z + box.height

    out: dict[str, tuple[float, float]] = {}
    edge: float | None = None
    for number in sorted(set(floor_of.values())):
        members = [b for b in boxes if floor_of.get(b.area) == number]
        if not members:
            continue
        low = min(reach(b)[0] for b in members)
        high = max(reach(b)[1] for b in members)
        step = 0.0 if edge is None else edge + EXPLODE_GAP - low
        edge = high + step
        # (step, step) as the view sees it, turned back to the house grid; the
        # page is twice as far up as either
        shift = (
            (step, step),
            (step, -step),
            (-step, -step),
            (-step, step),
        )[view % 4]
        for box in members:
            out[box.area] = shift
    return out


def _top_down_shifts(
    boxes: list[Box], floor_of: dict[str, int], view: int
) -> dict[str, tuple[float, float]]:
    """How far to move each room (east, north) to draw the floors apart from above.

    As ``_floor_shifts``, but for a plan: the lowest floor stays put, and each
    one above goes up the page until it is ``EXPLODE_GAP`` clear of the one before.
    """
    back = (4 - view % 4) % 4  # the turn that undoes the view's

    def reach(box: Box) -> tuple[float, float]:
        ups = [
            _turn(box.x + dx, box.y + dy, view)[1]
            for dx in (0.0, box.width)
            for dy in (0.0, box.depth)
        ]
        return min(ups), max(ups)

    out: dict[str, tuple[float, float]] = {}
    edge: float | None = None
    for number in sorted(set(floor_of.values())):
        members = [b for b in boxes if floor_of.get(b.area) == number]
        if not members:
            continue
        low = min(reach(b)[0] for b in members)
        high = max(reach(b)[1] for b in members)
        step = 0.0 if edge is None else edge + EXPLODE_GAP - low
        edge = high + step
        shift = _turn(0.0, step, back)
        for box in members:
            out[box.area] = shift
    return out


def _moved(point: Point, shift: tuple[float, float]) -> Point:
    return point[0] + shift[0], point[1] + shift[1], point[2]


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
    on the slope in the ``roofvalues`` layer (hidden with the roofs).

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
                _r_label(
                    tuple(middle),
                    roof.r_value_si,
                    unit,
                    defaults.get("roof_r"),
                    "roofvalues",
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
    """The points overlays draw at, worked out on the rooms as drawn (``drawn``:
    moved, when the floors are apart).

    Which rooms touch is found where they really are (``real``), so drawing
    the floors apart doesn't lose a room above another. ``real`` and ``drawn``
    are the same boxes in order (a stairs room is two boxes, its flight and its
    opening, one on each floor it occupies). Each anchor is:

    * ``data-room``: the room's centre, half way up;
    * ``data-between="a|b"`` (the two areas, sorted): the middle of the wall
      two rooms share, half way up the height they share; or, for a room over
      another, the middle of the floor between them (half way from one to
      the other when the floors are apart);
    * ``data-outside="area|face"``: the middle of each face with an outside
      wall part, half way up;
    * ``data-register`` (its part id), with ``data-room``: each outlet.
    """
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
    for (i, a), (j, b) in itertools.combinations(enumerate(real), 2):
        key = _pair(a.area, b.area)
        if a.area == b.area or key in seen:
            continue
        la = drawn[i]  # a side anchor follows the first room's floor
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
        lo, up = (drawn[i], drawn[j]) if a.z <= b.z else (drawn[j], drawn[i])
        z = (lo.z + lo.height + up.z) / 2
        # half way between where the two rooms are drawn
        dx = (lo.x - lower.x + up.x - upper.x) / 2
        dy = (lo.y - lower.y + up.y - upper.y) / 2
        scene.anchors.append(
            Anchor(((x0 + x1) / 2 + dx, (y0 + y1) / 2 + dy, z), {"between": key})
        )
        seen.add(key)


def _add_room_anchors(
    scene: Scene,
    box: Box,
    here: Box,
    where: dict[str, Box],
    parts: Parts,
    rotation: float,
) -> None:
    """The anchors of ``_add_anchors`` for a room drawn alone, so overlays such
    as the temperature difference can draw on it: its centre, the middle of each
    outside face, and, for each neighbour, the middle of the wall (or floor, or
    ceiling) between them with an anchor for the neighbour itself just past it
    (it is not drawn). ``box`` is the room where it is drawn, ``here`` where it
    is in the house, ``where`` every room as placed in the house."""
    area = box.area
    centre = (box.x + box.width / 2, box.y + box.depth / 2, box.z + box.height / 2)
    scene.anchors.append(Anchor(centre, {"room": area}))
    faces = {_face_of(wall, rotation) for wall in parts.walls.get(area, [])}
    for face in sorted(faces):
        point = _on_face(box, face, _span(box, face) / 2, box.height / 2)
        scene.anchors.append(Anchor(point, {"outside": f"{area}|{face}"}))
    for other, there in where.items():
        if other == area:
            continue
        key = _pair(area, other)
        side = _shared_face(here, there)
        if side is not None:
            face, start, end = side
            low, high = _overlap(
                here.z, here.z + here.height, there.z, there.z + there.height
            )
            point = _on_face(box, face, (start + end) / 2, (low + high) / 2 - here.z)
            # the neighbour, as far past the wall as the wall is from the middle
            beyond = (2 * point[0] - centre[0], 2 * point[1] - centre[1], point[2])
            scene.anchors.append(Anchor(point, {"between": key}))
            scene.anchors.append(Anchor(beyond, {"room": other}))
            continue
        up = abs(there.z - (here.z + here.height)) < TOUCH
        down = abs(here.z - (there.z + there.height)) < TOUCH
        if not (up or down):
            continue
        x0, x1 = _overlap(here.x, here.x + here.width, there.x, there.x + there.width)
        y0, y1 = _overlap(here.y, here.y + here.depth, there.y, there.y + there.depth)
        if x1 - x0 <= 0.3 or y1 - y0 <= 0.3:
            continue
        z = box.z + box.height if up else box.z
        rise = LINK_RISE if up else -LINK_RISE
        scene.anchors.append(Anchor((centre[0], centre[1], z), {"between": key}))
        scene.anchors.append(Anchor((centre[0], centre[1], z + rise), {"room": other}))


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
    shifts: dict[str, tuple[float, float]] | None = None,
) -> None:
    """Each register's run from the plenum, and a check of its length.

    ``boxes`` are where the rooms really are. With ``shifts`` (floors drawn
    apart: how far each room is moved), each run is drawn to its outlet
    on the moved floor, but its length is still measured where the rooms
    really are. The plenum moves with the floor it is on (the highest floor at
    or below its height).
    """
    shifts = shifts or {}
    registers = [e for e in elements.values() if e.kind == REGISTER]
    plenum = _plenum(house)
    if plenum is None:
        if registers:
            scene.notes.append(
                "Type the plenum's position in the house form to draw the runs."
            )
        return
    under = [b for b in boxes if b.z <= plenum[2] + 1e-6] or boxes
    home = max(under, key=lambda b: b.z, default=None) if shifts else None
    plenum_shift = shifts.get(home.area, (0.0, 0.0)) if home else (0.0, 0.0)
    scene.dots.append(Dot(_moved(plenum, plenum_shift), "#222222", "Plenum"))
    by_area = {box.area: box for box in boxes}
    for reg in sorted(registers, key=lambda e: e.title):
        box = by_area.get(reg.area_id or "")
        if box is None:
            scene.notes.append(f"{reg.title}: its room is not drawn, so no run")
            continue
        target = _outlet(box, reg)
        path = [plenum, (target[0], target[1], plenum[2]), target]
        drawn = sum(_distance(a, b) for a, b in itertools.pairwise(path)) / FOOT
        if shifts:
            shift = shifts.get(box.area, (0.0, 0.0))
            path = [
                _moved(path[0], plenum_shift),
                _moved(path[1], shift),
                _moved(target, shift),
            ]
        scene.lines.append(Run(path, colours[reg.id]))
        if reg.duct:
            feet = sum(seg.get("length_ft", 0.0) for seg in reg.duct)
            stated = f"duct {feet:.0f} ft" + (" (its branch)" if reg.upstream else "")
        else:
            stated = "no duct typed"
        scene.notes.append(f"{reg.title}: run {drawn:.0f} ft drawn, {stated}")


def _north(
    rotation: float, view: int = 0, top_down: bool = False
) -> tuple[float, float]:
    """True north on the page: the house's y axis turned back by its rotation."""
    turn = math.radians(rotation)
    dx, dy = project((-math.sin(turn), math.cos(turn), 0.0), view, top_down)
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


Rect = tuple[float, float, float, float]  # a box on the page: left, right, top, bottom
DOT_RADIUS = 6.0  # px: a dot's circle with its outline
LABEL_STEP = 1.3  # a label moved to clear another goes this many text sizes
MOVES = 8  # the most steps a label is moved, up or down, to clear the others


def _around(x: float, y: float, radius: float) -> Rect:
    return (x - radius, x + radius, y - radius, y + radius)


def _text_box(x: float, y: float, text: str, note: str, size: float) -> Rect:
    """About where a label's text is on the page, centred on (x, y): the text
    at ``0.62`` of its size a character (a bold sans-serif), its footnote smaller."""
    width = 0.62 * size * (len(text) + 0.7 * len(note))
    return (x - width / 2, x + width / 2, y - 0.8 * size, y + 0.2 * size)


def _clear_shift(box: Rect, taken: list[Rect], step: float) -> float:
    """How far to move a label up or down (px) to clear what is ``taken``: the
    least move, nearest first, that overlaps nothing; no move if none does."""
    for n in range(MOVES + 1):
        for sign in (1,) if n == 0 else (1, -1):
            shift = sign * n * step
            moved = (box[0], box[1], box[2] + shift, box[3] + shift)
            if not any(_meet(moved, other) for other in taken):
                return shift
    return 0.0


def _meet(a: Rect, b: Rect) -> bool:
    """Whether two boxes overlap (touching is not overlapping)."""
    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


def render(scene: Scene, width: int = 900) -> str:
    """The scene as an SVG, the captions under the drawing."""
    view, top_down = scene.view, scene.top_down

    def on_page(point: Point) -> tuple[float, float]:
        return project(point, view, top_down)

    def upright(poly: Poly) -> bool:
        """A wall, window or door: not all at one height, a line from above."""
        return len({round(p[2], 6) for p in poly.points}) > 1

    polygons = scene.polygons
    if top_down:
        # from above, the floors first, then every wall over them (floors cover
        # the walls drawn before them otherwise)
        polygons = sorted(polygons, key=upright)
    corners = [on_page(p) for poly in polygons for p in poly.points]
    corners += [on_page(p) for run in scene.lines for p in run.points]
    corners += [on_page(dot.point) for dot in scene.dots]
    xs = [x for x, _ in corners] or [0.0]
    ys = [y for _, y in corners] or [0.0]
    left, top = min(xs), min(ys)
    span_x = max(max(xs) - left, 1.0)
    span_y = max(max(ys) - top, 1.0)
    # the margins (left, top, right, bottom) start at MARGIN and grow until every
    # label's text is inside the picture, so no label is cut off at its edge
    pads = [MARGIN, MARGIN, MARGIN, MARGIN]
    text_size = 11 * scene.text_scale
    right_edge = width - NORTH_COLUMN - MARGIN
    for _ in range(6):
        scale = min(
            (width - NORTH_COLUMN - pads[0] - pads[2]) / span_x,
            (scene.height - pads[1] - pads[3]) / span_y,
        )
        for label in scene.labels:
            if not label.text:
                continue
            px, py = on_page(label.point)
            x = pads[0] + (px - left) * scale
            y = pads[1] + (py - top) * scale
            box_l, box_r, box_t, box_b = _text_box(
                x, y, label.text, label.note, text_size
            )
            pads[0] += max(0.0, MARGIN - box_l)
            pads[1] += max(0.0, MARGIN - box_t)
            pads[2] += max(0.0, box_r - right_edge)
            pads[3] = max(pads[3], box_b - (pads[1] + span_y * scale) + MARGIN)
    draw_h = pads[1] + span_y * scale + pads[3]

    def at(point: Point) -> str:
        x, y = on_page(point)
        return f"{pads[0] + (x - left) * scale:.1f},{pads[1] + (y - top) * scale:.1f}"

    # the order the layers are drawn in: the roofs over the rooms and runs
    layers: dict[str, list[str]] = {"rooms": [], "runs": [], "roofs": []}
    for poly in polygons:
        dash = f' stroke-dasharray="{poly.dasharray}"' if poly.dashed else ""
        stroke = TOP_WALL_WIDTH if top_down and upright(poly) else 1.2
        layers.setdefault(poly.layer, []).append(
            f'<polygon points="{" ".join(at(p) for p in poly.points)}" '
            f'fill="{poly.fill}" fill-opacity="{poly.opacity}" '
            f'stroke="{poly.stroke}" stroke-width="{stroke:g}"{dash}/>'
        )
    for run in scene.lines:
        dash = f' stroke-dasharray="{run.dasharray}"' if run.dasharray else ""
        layers.setdefault(run.layer, []).append(
            f'<polyline points="{" ".join(at(p) for p in run.points)}" fill="none" '
            f'stroke="{run.colour}" stroke-width="{run.width}"{dash} '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    taken: list[Rect] = []  # where the dots and labels already are, on the page
    for dot in scene.dots:
        x, y = at(dot.point).split(",")
        taken.append(_around(float(x), float(y), DOT_RADIUS))
        layers.setdefault(dot.layer, []).append(
            f'<circle cx="{x}" cy="{y}" r="4.5" fill="{dot.colour}" '
            f'stroke="#ffffff" stroke-width="1.5">'
            f"<title>{escape(dot.label, quote=False)}</title></circle>"
        )
    size = 11 * scene.text_scale
    for label in scene.labels:
        if not label.text:
            continue
        x, y = (float(v) for v in at(label.point).split(","))
        box = _text_box(x, y, label.text, label.note, size)
        shift = _clear_shift(box, taken, size * LABEL_STEP)
        taken.append((box[0], box[1], box[2] + shift, box[3] + shift))
        note = (
            f'<tspan baseline-shift="super" font-size="70%">{label.note}</tspan>'
            if label.note
            else ""
        )
        layers.setdefault(label.layer, []).append(
            f'<text x="{x:.1f}" y="{y + shift:.1f}" fill="#222222" '
            f'font-size="{size:g}" font-weight="600" '
            'text-anchor="middle" stroke="#ffffff" '
            f'stroke-width="{3 * scene.text_scale:g}" '
            f'paint-order="stroke">{escape(label.text, quote=False)}{note}</text>'
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
    footnotes = {label.note for label in scene.labels}
    if "a" in footnotes:
        notes.append(SIZE_NOTE)
    if "b" in footnotes:
        notes.append(DEFAULT_NOTE)
    if "c" in footnotes:
        notes.append(WORKED_NOTE)
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


def _add_connections(
    scene: Scene, drawn: list[Box], elements: dict[str, Element]
) -> None:
    """The ``connections`` and ``names`` layers of a plan.

    Each link a room is given (beside, above or below, or an internal wall)
    is a line between the middles of the two rooms' floors, dashed when
    they are open to each other; a link to a room not drawn is left out. Each
    room's name is on the middle of its floor. ``drawn`` are the rooms as drawn
    (a stairs room's first box is its flight). The names go after every other
    label, so they move out of the way rather than move the others.
    """
    first: dict[str, Box] = {}
    for box in drawn:
        first.setdefault(box.area, box)

    def middle(box: Box) -> Point:
        return (box.x + box.width / 2, box.y + box.depth / 2, box.z)

    seen: set[str] = set()
    for area, items in neighbours(elements).items():
        for link in items:
            other = link["area_id"]
            key = _pair(area, other)
            if key in seen or area not in first or other not in first:
                continue
            seen.add(key)
            scene.lines.append(
                Run(
                    [middle(first[area]), middle(first[other])],
                    CONNECTION_COLOUR,
                    2.0,
                    "connections",
                    CONNECTION_DASH if link["open"] else "",
                )
            )
    for box in first.values():
        floor = (box.x + box.width / 2, box.y + box.depth / 2, box.z)
        scene.labels.append(Label(floor, box.title, "names"))


def _position_text(x: float, y: float, unit: str) -> str:
    """Where a point is from the origin, along the house grid: ``4 m E, 1.5 m N``."""
    east = f"{format_size(abs(x), unit)} {'W' if x < 0 else 'E'}"
    north = f"{format_size(abs(y), unit)} {'S' if y < 0 else 'N'}"
    return f"{east}, {north}"


def _add_positions(scene: Scene, pinned: list[tuple[Box, Box]], unit: str) -> None:
    """The ``positions`` layer of a plan.

    The origin (the house's south-west corner) is a dot on the lowest floor
    drawn, when it is among the rooms drawn. Each room with a typed position
    has a pin on its floor's south-west corner, labelled with that position.
    ``pinned`` are each room's box where it is, and where it is drawn (moved
    up the page when the floors are drawn apart). A room fitted to the others
    has no pin.
    """
    drawn = [moved for _, moved in pinned]
    if drawn:
        east = min(b.x for b in drawn), max(b.x + b.width for b in drawn)
        north = min(b.y for b in drawn), max(b.y + b.depth for b in drawn)
        if east[0] <= 0.0 <= east[1] and north[0] <= 0.0 <= north[1]:
            origin = (0.0, 0.0, min(b.z for b in drawn))
            scene.dots.append(
                Dot(
                    origin,
                    ORIGIN_COLOUR,
                    "Origin: the house's south-west corner, where positions "
                    "are measured from",
                    "positions",
                )
            )
            scene.labels.append(Label(origin, "origin", "positions"))
    for box, moved in pinned:
        if not box.fixed:
            continue
        text = _position_text(box.x, box.y, unit)
        corner = (moved.x, moved.y, moved.z)
        scene.dots.append(
            Dot(corner, POSITION_COLOUR, f"{box.title}: at {text}", "positions")
        )
        scene.labels.append(Label(corner, text, "positions"))


def _head(start: Point, end: Point) -> list[Point]:
    """The two short lines of an arrowhead at ``end``, pointing back along the arrow."""
    d = [e - s for s, e in zip(start, end, strict=True)]
    n = math.hypot(*d) or 1.0
    d = [v / n for v in d]
    # across the arrow: horizontal, or east for one pointing straight up or down
    side = (-d[1], d[0], 0.0) if math.hypot(d[0], d[1]) > 1e-9 else (1.0, 0.0, 0.0)
    back = [end[i] - d[i] * LINK_HEAD for i in range(3)]
    wing = [side[i] * LINK_HEAD / 2 for i in range(3)]
    return [
        tuple(back[i] + wing[i] for i in range(3)),
        end,
        tuple(back[i] - wing[i] for i in range(3)),
    ]


def _add_links(
    scene: Scene,
    box: Box,
    elements: dict[str, Element],
    where: dict[str, Box],
    links: list[dict],
) -> None:
    """Arrows from a room towards each room it links to, each labelled with its name.

    A room beside it (or open to it) gets an arrow out from the room's middle,
    in the direction of that room, through the wall between; a room above or below
    gets an arrow straight up or down. A neighbour with no size is not drawn, and
    a note says so. ``box`` is the room where it is drawn, ``where`` the rooms as
    they are placed in the house.
    """
    titles = {e.area_id: e.title for e in elements.values() if e.kind == ROOM}
    me = where.get(box.area)
    if me is None:
        return
    cx, cy = box.x + box.width / 2, box.y + box.depth / 2
    mid = box.z + box.height / 2
    for link in links:
        other = link["area_id"]
        name = titles.get(other, other)
        if link["position"] == ABOVE:
            top = box.z + box.height
            start, end = (cx, cy, top), (cx, cy, top + LINK_RISE)
            label = f"above: {name}"
        elif link["position"] == BELOW:
            start, end = (cx, cy, box.z), (cx, cy, box.z - LINK_RISE)
            label = f"below: {name}"
        else:
            there = where.get(other)
            if there is None:
                scene.notes.append(f"Link to {name}: not drawn, it has no size yet.")
                continue
            dx = there.x + there.width / 2 - (me.x + me.width / 2)
            dy = there.y + there.depth / 2 - (me.y + me.depth / 2)
            n = math.hypot(dx, dy)
            if n < 1e-6:  # on top of each other: no direction to point in
                continue
            ux, uy = dx / n, dy / n
            # from the middle out past the wall that faces it
            reach = (
                min(
                    (box.width / 2) / abs(ux) if abs(ux) > 1e-9 else math.inf,
                    (box.depth / 2) / abs(uy) if abs(uy) > 1e-9 else math.inf,
                )
                + LINK_REACH
            )
            start = (cx, cy, mid)
            end = (cx + ux * reach, cy + uy * reach, mid)
            label = f"{name} (open)" if link["open"] else name
        scene.lines.append(Run([start, end], LINK_COLOUR, 2.0, "links"))
        scene.lines.append(Run(_head(start, end), LINK_COLOUR, 2.0, "links"))
        scene.labels.append(Label((end[0], end[1], end[2] + 0.2), label, "links"))


def room_svg(
    elements: dict[str, Element],
    house: dict,
    area_id: str,
    view: int = 0,
    defaults: dict[str, float] | None = None,
    large_text: bool = False,
    floors: dict[str, int] | None = None,
    outline: list[tuple[float, float]] | None = None,
    buildings: list[Any] | None = None,
    top_down: bool = False,
) -> str | None:
    """One room's isometric drawing, or None when the area has no room part.

    ``view`` turns the view by quarter turns (see ``VIEWS``); ``top_down``
    draws it from straight above instead (see ``project``). ``large_text``
    draws the labels (sizes, R-values) at ``LARGE_TEXT`` times their size.
    Arrows show the rooms it links to (see ``_add_links``). ``floors``,
    ``outline`` and ``buildings`` are as for ``house_svg``: the room is drawn
    the size and shape it has in the house.
    """
    room = next(
        (e for e in elements.values() if e.kind == ROOM and e.area_id == area_id),
        None,
    )
    if room is None:
        return None
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    scene = Scene(
        north=_north(rotation, view, top_down),
        view=view % 4,
        top_down=top_down,
        text_scale=LARGE_TEXT if large_text else 1.0,
    )
    if _footprint(room) is None:
        scene.notes.append(
            f"{room.title}: no size yet. Type its width and depth, or its floor area."
        )
        return render(scene)
    parts = _parts(elements)
    placed, _ = _place(elements, unit, floors, rotation, outline, buildings)
    where = {b.area: b for b in placed}
    # the room as it is in the house (shaped to fit, if it has no width or depth)
    box = replace(where[area_id], x=0.0, y=0.0, z=0.0)
    inside, door_notes = _inside_parts(elements, parts, area_id, where)
    links = _link_stretches(elements, parts, area_id, where)
    floor_of = _floor_index(elements, set(where), floors)
    beside = [b for b in placed if floor_of.get(b.area) == floor_of.get(area_id)]
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
        links=links,
        against=_against(where[area_id], beside),
        wing_inside=_wing_parts(parts, area_id, where),
    )
    _add_roofs(scene, [box], elements, rotation, unit, defaults)
    _add_room_anchors(
        scene,
        box,
        where[area_id],
        where,
        parts,
        rotation,
    )
    scene.notes.extend(box.notes)
    scene.notes.extend(door_notes)
    _add_links(scene, box, elements, where, neighbours(elements).get(area_id, []))
    missing = _dashed_faces(box, rotation, parts, inside, links)
    if missing:
        scene.notes.append(
            "Dashed faces have no wall part yet: " + ", ".join(missing) + "."
        )
    if any(kind == "open" for *_, kind in links) or any(
        item.open_link for item, *_ in inside if item.kind == INTERNAL_WALL
    ):
        scene.notes.append("Dotted faces are open (no wall) to a neighbour.")
    if any(kind == "implied" for *_, kind in links):
        scene.notes.append(
            "Dash-dotted faces share a neighbour with no internal wall typed yet."
        )
    scene.notes.append(
        f"{_looking(view, top_down)} Windows and doors (brown) sit centred, "
        f"window sills at {SILL:g} m."
    )
    return render(scene)


def _looking(view: int, top_down: bool) -> str:
    """The caption that says where the drawing is seen from."""
    if top_down:
        return f"From above, {UP_BY_VIEW[view % 4]} at the top."
    return f"Looking from the {VIEWS[view % 4]}."


def _notes_for(
    notes: list[str], elements: dict[str, Element], only: set[str]
) -> list[str]:
    """The placing notes that are about drawn rooms, or about no room (a note
    names its room first, as ``"Kitchen: ..."``)."""
    away = {
        e.title for e in elements.values() if e.kind == ROOM and e.area_id not in only
    }
    return [n for n in notes if n.partition(": ")[0] not in away]


def house_svg(
    elements: dict[str, Element],
    house: dict,
    exploded: bool = False,
    view: int = 0,
    floors: dict[str, int] | None = None,
    defaults: dict[str, float] | None = None,
    only: set[str] | None = None,
    outline: list[tuple[float, float]] | None = None,
    buildings: list[Any] | None = None,
    large_text: bool = False,
    level: int | None = None,
    top_down: bool = False,
) -> str:
    """The house from its rooms at their positions, with the heating runs on it.

    ``top_down`` draws it from straight above (see ``project``). Floors seen
    from above would lie over each other, so with more than one they are
    always drawn apart, one above the other up the page.

    The floors are drawn stacked, each room over the ones below it.
    ``exploded`` draws them apart instead, one above the other up the page
    (on a sheet as many times taller), so an upper floor doesn't hide the one
    under it. The runs are drawn to the
    moved floors but measured on the real ones. ``view`` turns the view by
    quarter turns (see ``VIEWS``). ``floors`` gives each area's floor level,
    which says which rooms share a floor.

    ``outline`` is the building outline's corners in the house's grid, and
    ``buildings`` the detached buildings, with where each sits (see ``_place``).

    ``only`` draws just those areas' rooms (a floor or a detached building),
    still at their places in the whole house; their registers and runs go too.
    ``large_text`` draws the labels at ``LARGE_TEXT`` times their size, as for a room.

    ``level`` draws just one floor (its rooms, by ``floors``; with ``only``, those
    rooms, as two floors can share a level). Stairs that reach
    it show their part of it: the flight, if it is the lower floor, else the
    opening in its upper floor. Stairs are drawn as a flight on the lower floor
    and an opening on the one above, in the same place.
    """
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    boxes, notes = _place(elements, unit, floors, rotation, outline, buildings)
    if level is not None and floors is not None:
        # the floor's own rooms, where given: another floor can share its level
        floor = only

        def on_level(area: str) -> bool:
            if floor is not None:
                return area in floor
            return floors.get(area) == level

        only = {
            b.area
            for b in boxes
            if on_level(b.floor_area or b.area)
            or (b.top_area is not None and on_level(b.top_area))
        }
    if only is not None:
        notes = _notes_for(notes, elements, only)
        boxes = [b for b in boxes if b.area in only]
        elements = {
            k: e for k, e in elements.items() if e.kind != REGISTER or e.area_id in only
        }
    # each floor (by its floor, or its height) goes up the page from the one below
    floor_of = _floor_index(elements, {b.area for b in boxes}, floors)
    apart = (exploded or top_down) and len(set(floor_of.values())) > 1
    spread = _top_down_shifts if top_down else _floor_shifts
    shifts = spread(boxes, floor_of, view) if apart else {}
    drawn = [
        replace(
            b,
            x=b.x + shifts.get(b.floor_area or b.area, (0.0, 0.0))[0],
            y=b.y + shifts.get(b.floor_area or b.area, (0.0, 0.0))[1],
        )
        for b in boxes
    ]

    def flight_here(box: Box) -> bool:
        return (
            level is None
            or floors is None
            or floors.get(box.floor_area or box.area) == level
        )

    def opening_here(box: Box) -> bool:
        return box.top_z is not None and (
            level is None or floors is None or floors.get(box.top_area or "") == level
        )

    colours = _colours(elements)
    parts = _parts(elements)
    where = {b.area: b for b in boxes}
    scene = Scene(
        north=_north(rotation, view, top_down),
        view=view % 4,
        top_down=top_down,
        text_scale=LARGE_TEXT if large_text else 1.0,
    )
    if apart:
        scene.height = SHEET_HEIGHT * len(set(floor_of.values()))
    # the boxes overlays point at: a stairs room is its flight and its opening
    real: list[Box] = []
    layers: list[Box] = []
    for box, moved in zip(boxes, drawn, strict=True):
        if flight_here(box):
            real.append(box)
            layers.append(moved)
        if opening_here(box):
            dx, dy = shifts.get(box.top_area or "", (0.0, 0.0))
            real.append(replace(box, z=box.top_z))
            layers.append(replace(box, x=box.x + dx, y=box.y + dy, z=box.top_z))
    for box in sorted(drawn, key=lambda b: _depth_key(b, view)):
        if not flight_here(box):
            continue
        inside, door_notes = _inside_parts(elements, parts, box.area, where)
        links = _link_stretches(elements, parts, box.area, where)
        beside = [b for b in boxes if floor_of.get(b.area) == floor_of.get(box.area)]
        _add_room(
            scene,
            box,
            rotation,
            parts,
            colours,
            inside,
            unit,
            defaults=defaults,
            links=links,
            against=_against(where[box.area], beside),
            wing_inside=_wing_parts(parts, box.area, where),
        )
        notes.extend(door_notes)
    # stairs' openings on the floor above, where their flights come up to it
    for box in boxes:
        if box.top_z is not None and opening_here(box):
            dx, dy = shifts.get(box.top_area or "", (0.0, 0.0))
            top = replace(box, x=box.x + dx, y=box.y + dy, z=box.top_z)
            scene.polygons.append(Poly(_floor(top), OPENING_FILL, OPENING_LINE, 1.0))
    # the plenum goes with the floor it is on; each run's outlet with its own
    _add_runs(scene, boxes, elements, house, colours, shifts)
    _add_roofs(scene, drawn, elements, rotation, unit, defaults)
    _add_anchors(scene, real, layers, parts, rotation)
    _add_connections(scene, layers, elements)
    _add_positions(
        scene,
        [(b, moved) for b, moved in zip(boxes, drawn, strict=True) if flight_here(b)],
        unit,
    )
    if not boxes:
        notes.append("No rooms are drawn yet.")
    key = _looking(view, top_down)
    if apart:
        key += (
            " Floors drawn apart: one above the other up the page, the lowest "
            "at the bottom, so the runs between floors are not to scale."
        )
    scene.notes = [key, *notes, *scene.notes]
    return render(scene)
