# Copyright (c) 2026 MinchinWeb
"""Isometric drawings: each room, the house from its rooms, and the heating runs.

Standard library only, so the tests run without Home Assistant.

The frame is the house grid: x runs east and y north along the house's own
faces (its N face is the wall at the top of each room's footprint), z is height,
and the origin is the house's south-west corner on the ground. The drawing looks
down from the south-west, so east runs right and away, and north left and away.
Compass north is drawn as an arrow, from the house rotation.

A room is a box of its footprint and ceiling height. Its outside walls are
drawn on their faces (a face with no wall part is dashed), its windows are
centred on their walls with the sill at ``SILL``, and its registers are dots.
The house view places each room at its position and floor level, and draws each
register's run from the plenum: straight across at the plenum's height, then up
or down to the outlet. The runs are schematic (they do not follow the joists or
the walls), so the length shown is the drawn run, listed beside the duct's own
stated length as a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import itertools
import math
import textwrap
from typing import NamedTuple

from .constants import REGISTER, ROOM, WALL, WINDOW
from .geometry import FACES, FOOT, format_size
from .model import Element

COS30 = math.sqrt(3) / 2
SIN30 = 0.5
DEFAULT_CEILING = 2.4  # m, where no ceiling height is given
DEFAULT_GLASS = (0.9, 1.2)  # m wide and high, where a window has no size
SILL = 0.9  # m above the floor, for a window's sill
DEFAULT_OUTLET = 0.1  # m above the floor, where a register has no height
GAP = 1.0  # m between rooms drawn in a row (no position typed)
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
MISSING_LINE = "#b0a58c"
FACE_ORDER = ("N", "E", "S", "W")  # far faces first, so the near ones overlay them
NEAR_FACES = ("S", "W")

Point = tuple[float, float, float]  # metres in the house grid


class Poly(NamedTuple):
    """A flat shape: its corners, fill and outline."""

    points: list[Point]
    fill: str
    stroke: str
    opacity: float = 1.0
    dashed: bool = False


class Run(NamedTuple):
    """A polyline (a duct run)."""

    points: list[Point]
    colour: str
    width: float = 2.6


class Dot(NamedTuple):
    """A point with a label (an outlet, the plenum)."""

    point: Point
    colour: str
    label: str = ""


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


@dataclass
class Scene:
    """What to draw, and the caption under it."""

    polygons: list[Poly] = field(default_factory=list)
    lines: list[Run] = field(default_factory=list)
    dots: list[Dot] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    north: tuple[float, float] | None = None  # the direction of true north, on the page


def project(point: Point) -> tuple[float, float]:
    """Where a point of the house grid sits on the page (y grows downwards)."""
    x, y, z = point
    return (x - y) * COS30, -(x + y) * SIN30 - z


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


def _window_quads(box: Box, face: str, windows: list[Element]) -> list[list[Point]]:
    """The windows of one wall, centred on it in a row, sills at ``SILL``."""
    sizes = [
        (
            w.glass_width_m or DEFAULT_GLASS[0],
            w.glass_height_m or DEFAULT_GLASS[1],
        )
        for w in windows
    ]
    span = _span(box, face)
    total = sum(width for width, _ in sizes)
    scale = min(1.0, 0.9 * span / total) if total else 1.0
    along = (span - total * scale) / 2
    quads = []
    for width, height in sizes:
        width *= scale
        z0 = max(0.1, min(SILL, box.height - height - 0.1))
        z1 = min(z0 + height, box.height - 0.05)
        quads.append(_quad(box, face, along, along + width, z0, z1))
        along += width
    return quads


def _outlet(box: Box, reg: Element) -> Point:
    """Where a register's outlet is on the plan: centred and at the floor if untyped."""
    x = box.width / 2 if reg.at_x_m is None else reg.at_x_m
    y = box.depth / 2 if reg.at_y_m is None else reg.at_y_m
    z = DEFAULT_OUTLET if reg.at_z_m is None else reg.at_z_m
    return box.x + x, box.y + y, box.z + z


def _parts(elements: dict[str, Element]):
    """The walls of each room, the windows of each wall, the outlets of each room."""
    walls: dict[str, list[Element]] = {}
    windows: dict[str, list[Element]] = {}
    outlets: dict[str, list[Element]] = {}
    for e in elements.values():
        if e.kind == WALL:
            walls.setdefault(e.area_id or "", []).append(e)
        elif e.kind == WINDOW and e.host in elements:
            if elements[e.host].kind == WALL:  # a skylight is not drawn
                windows.setdefault(e.host, []).append(e)
        elif e.kind == REGISTER:
            outlets.setdefault(e.area_id or "", []).append(e)
    return walls, windows, outlets


def _colours(elements: dict[str, Element]) -> dict[str, str]:
    """A colour for each register's outlet and run, the same in every drawing."""
    registers = sorted(
        (e for e in elements.values() if e.kind == REGISTER), key=lambda e: e.id
    )
    return {
        reg.id: RUN_COLOURS[i % len(RUN_COLOURS)] for i, reg in enumerate(registers)
    }


def _add_room(scene: Scene, box: Box, rotation: float, parts, colours) -> None:
    """Draw one room's floor, walls, windows and outlets (far faces first)."""
    walls, windows, outlets = parts
    # an upper floor is see-through, so the room below shows through it
    floor_opacity = 0.7 if box.z > 0 else 1.0
    scene.polygons.append(Poly(_floor(box), FLOOR_FILL, FLOOR_LINE, floor_opacity))
    by_face: dict[str, list[Element]] = {face: [] for face in FACE_ORDER}
    for wall in walls.get(box.area, []):
        by_face[_face_of(wall, rotation)].append(wall)
    for face in FACE_ORDER:
        opacity = 0.6 if face in NEAR_FACES else 0.9
        if not by_face[face]:
            outline = _quad(box, face, 0.0, _span(box, face), 0.0, box.height)
            scene.polygons.append(Poly(outline, "none", MISSING_LINE, 1.0, True))
            continue
        for wall in by_face[face]:
            outline = _quad(box, face, 0.0, _span(box, face), 0.0, box.height)
            scene.polygons.append(Poly(outline, WALL_FILL, WALL_LINE, opacity))
            for glass in _window_quads(box, face, windows.get(wall.id, [])):
                scene.polygons.append(Poly(glass, WINDOW_FILL, WINDOW_LINE, 0.9))
    for reg in outlets.get(box.area, []):
        scene.dots.append(Dot(_outlet(box, reg), colours[reg.id], reg.title))


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


def _depth_key(box: Box) -> float:
    """Draw far and low rooms first: the painter's order from the south-west."""
    return 2 * box.z - (box.x + box.width / 2 + box.y + box.depth / 2)


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
) -> None:
    """Each register's run from the plenum, and a check of its length."""
    registers = [e for e in elements.values() if e.kind == REGISTER]
    plenum = _plenum(house)
    if plenum is None:
        if registers:
            scene.notes.append(
                "Type the plenum's position in the house form to draw the runs."
            )
        return
    scene.dots.append(Dot(plenum, "#222222", "Plenum"))
    by_area = {box.area: box for box in boxes}
    for reg in sorted(registers, key=lambda e: e.title):
        box = by_area.get(reg.area_id or "")
        if box is None:
            scene.notes.append(f"{reg.title}: its room is not drawn, so no run")
            continue
        target = _outlet(box, reg)
        path = [plenum, (target[0], target[1], plenum[2]), target]
        drawn = sum(_distance(a, b) for a, b in itertools.pairwise(path)) / FOOT
        scene.lines.append(Run(path, colours[reg.id]))
        if reg.duct:
            feet = sum(seg.get("length_ft", 0.0) for seg in reg.duct)
            stated = f"duct {feet:.0f} ft" + (" (its branch)" if reg.upstream else "")
        else:
            stated = "no duct typed"
        scene.notes.append(f"{reg.title}: run {drawn:.0f} ft drawn, {stated}")


def _north(rotation: float) -> tuple[float, float]:
    """True north on the page: the house's y axis turned back by its rotation."""
    turn = math.radians(rotation)
    dx, dy = project((-math.sin(turn), math.cos(turn), 0.0))
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def render(scene: Scene, width: int = 360) -> str:
    """The scene as an SVG, the captions under the drawing."""
    corners = [project(p) for poly in scene.polygons for p in poly.points]
    corners += [project(p) for run in scene.lines for p in run.points]
    corners += [project(dot.point) for dot in scene.dots]
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
        x, y = project(point)
        return f"{MARGIN + (x - left) * scale:.1f},{MARGIN + (y - top) * scale:.1f}"

    out: list[str] = []
    for poly in scene.polygons:
        dash = ' stroke-dasharray="4 3"' if poly.dashed else ""
        out.append(
            f'<polygon points="{" ".join(at(p) for p in poly.points)}" '
            f'fill="{poly.fill}" fill-opacity="{poly.opacity}" '
            f'stroke="{poly.stroke}" stroke-width="1.2"{dash}/>'
        )
    for run in scene.lines:
        out.append(
            f'<polyline points="{" ".join(at(p) for p in run.points)}" fill="none" '
            f'stroke="{run.colour}" stroke-width="{run.width}" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    for dot in scene.dots:
        x, y = at(dot.point).split(",")
        out.append(
            f'<circle cx="{x}" cy="{y}" r="4.5" fill="{dot.colour}" '
            f'stroke="#ffffff" stroke-width="1.5">'
            f"<title>{escape(dot.label, quote=False)}</title></circle>"
        )
    if scene.north is not None:
        dx, dy = scene.north
        base_x, base_y = width - MARGIN - 6, MARGIN + 6
        tip_x, tip_y = base_x + 22 * dx, base_y + 22 * dy
        out.append(
            f'<line x1="{base_x:.1f}" y1="{base_y:.1f}" x2="{tip_x:.1f}" '
            f'y2="{tip_y:.1f}" stroke="#333333" stroke-width="2"/>'
            f'<text x="{tip_x + 4 * dx:.1f}" y="{tip_y + 4 * dy + 4:.1f}" '
            'fill="#333333" font-weight="bold">N</text>'
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
        f'font-family="sans-serif" font-size="12">{body}{"".join(lines)}</svg>'
    )


def room_svg(elements: dict[str, Element], house: dict, area_id: str) -> str | None:
    """One room's isometric drawing, or None when the area has no room part."""
    room = next(
        (e for e in elements.values() if e.kind == ROOM and e.area_id == area_id),
        None,
    )
    if room is None:
        return None
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    scene = Scene(north=_north(rotation))
    box = _box(room, 0.0, 0.0, 0.0, unit)
    if box is None:
        scene.notes.append(
            f"{room.title}: no size yet. Type its width and depth, or its floor area."
        )
        return render(scene)
    parts = _parts(elements)
    faces = {_face_of(w, rotation) for w in parts[0].get(area_id, [])}
    _add_room(scene, box, rotation, parts, _colours(elements))
    scene.notes.extend(box.notes)
    missing = [face for face in FACE_ORDER if face not in faces]
    if missing:
        scene.notes.append(
            "Dashed faces have no wall part yet: " + ", ".join(missing) + "."
        )
    scene.notes.append(
        f"Looking from the south-west. Windows sit centred, sills at {SILL:g} m."
    )
    return render(scene)


def house_svg(elements: dict[str, Element], house: dict) -> str:
    """The house from its rooms at their positions, with the heating runs on it."""
    rotation = float(house.get("rotation") or 0.0)
    unit = house.get("unit", "m")
    boxes, notes = _place(elements, unit)
    colours = _colours(elements)
    parts = _parts(elements)
    scene = Scene(north=_north(rotation))
    for box in sorted(boxes, key=_depth_key):
        _add_room(scene, box, rotation, parts, colours)
    _add_runs(scene, boxes, elements, house, colours)
    if not boxes:
        notes.append("No rooms are drawn yet.")
    key = "Looking from the south-west: east and north from the house's corner."
    scene.notes = [key, *notes, *scene.notes]
    return render(scene, width=420)
