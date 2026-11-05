# Copyright (c) 2026 MinchinWeb
"""The parts as a spreadsheet: CSV or tab-separated text to and from rows, and
the rooms' footprints, which say which rooms touch and which room faces are
outside.

A footprint is a room's place on the house's grid in metres: its south-west
corner (``x``, ``y``, north of and east of the house's corner), its size and
its floor's height. Two rooms on the same floor that share an edge are beside
each other; a room's ceiling is under the rooms above it that overlap it. Standard
library only, so the rules are tested without Home Assistant.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import csv
from dataclasses import dataclass
import io

# The columns, in the order they are written. Each is a form field of its part
# (see ``config_flow.py``), with sizes in the house's unit, except ``id``, which
# is the part's sub-entry id (a row with one changes that part), and ``kind``.
COLUMNS = (
    "id",
    "kind",
    "name",
    "room_type",
    "area_id",
    "area_ids",
    "other_area_id",
    "host",
    "face",
    "facing",
    "shade_below",
    "pitch",
    "length",
    "height",
    "slope",
    "width",
    "depth",
    "floor",
    "volume",
    "below_grade",
    "x",
    "y",
    "level",
    "below_ground",
    "beside",
    "above",
    "open",
    "transmittance",
    "blind",
    "blind_closed",
    "glazing",
    "frame",
    "r_imperial",
    "sensor",
    "climate",
    "fan",
    "free_area_in2",
    "flow_cfm",
    "duct",
    "upstream",
    "at_x",
    "at_y",
    "at_z",
)

# Edges this close (metres) are the same line.
TOLERANCE = 1e-6


def parse(text: str) -> list[tuple[int, dict[str, str]]]:
    """The rows of a sheet as ``(row number, {column: value})``.

    The first row is the header. Cells are separated by tabs (what a spreadsheet
    copies) when the header has one, otherwise by commas. Blank rows are skipped,
    and the row numbers count the rows that are not blank, below the header.

    Raises:
        ValueError: when there is no header, the header has no ``kind`` column, a
            column is unknown or repeated, or a row has more cells than the header.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("the sheet is empty")
    delimiter = "\t" if "\t" in lines[0] else ","
    cells = list(csv.reader(lines, delimiter=delimiter))
    headers = [cell.strip().lower() for cell in cells[0]]
    unknown = [h for h in headers if h not in COLUMNS]
    if unknown:
        names = ", ".join(repr(h) for h in unknown)
        raise ValueError(f"unknown column {names}")
    if "kind" not in headers:
        raise ValueError("the sheet needs a kind column")
    if len(set(headers)) != len(headers):
        raise ValueError("a column is in the sheet more than once")
    rows = []
    for number, row in enumerate(cells[1:], start=1):
        values = [cell.strip() for cell in row]
        if any(values[len(headers) :]):
            raise ValueError(f"row {number} has more cells than the header")
        named = {
            header: values[i] if i < len(values) else ""
            for i, header in enumerate(headers)
        }
        if any(named.values()):
            rows.append((number, named))
    return rows


def dump(rows: Iterable[dict[str, str]]) -> str:
    """The rows as CSV text, with the header of ``COLUMNS``."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else row[c] for c in COLUMNS])
    return out.getvalue()


@dataclass(frozen=True)
class Footprint:
    """A room's footprint, in metres on the house's grid."""

    area_id: str
    x: float
    y: float
    width: float
    depth: float
    level: float = 0.0

    @property
    def east(self) -> float:
        return self.x + self.width

    @property
    def north(self) -> float:
        return self.y + self.depth


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _touch(p: float, q: float) -> bool:
    return abs(p - q) <= TOLERANCE


def shared_length(a: Footprint, b: Footprint) -> float:
    """The length of wall two rooms share, in metres; 0 if they do not touch on
    one floor."""
    if not _touch(a.level, b.level):
        return 0.0
    total = 0.0
    if _touch(a.east, b.x) or _touch(b.east, a.x):
        total += _overlap(a.y, a.north, b.y, b.north)
    if _touch(a.north, b.y) or _touch(b.north, a.y):
        total += _overlap(a.x, a.east, b.x, b.east)
    return total


def overlap_area(a: Footprint, b: Footprint) -> float:
    """The floor both rooms take up, in square metres (0 if they do not overlap)."""
    return _overlap(a.x, a.east, b.x, b.east) * _overlap(a.y, a.north, b.y, b.north)


def links(
    rooms: Sequence[Footprint],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Each room's neighbours, as ``(beside, above)``.

    ``beside`` lists the rooms on its floor that share a wall with it. ``above``
    lists the rooms on the next floor up that its ceiling is under: those that
    overlap it there, on the lowest floor above it.
    """
    beside: dict[str, list[str]] = {}
    above: dict[str, list[str]] = {}
    for a in rooms:
        beside[a.area_id] = sorted(
            b.area_id
            for b in rooms
            if b.area_id != a.area_id and shared_length(a, b) > TOLERANCE
        )
        higher = [
            b
            for b in rooms
            if b.level > a.level + TOLERANCE and overlap_area(a, b) > TOLERANCE
        ]
        if higher:
            floor = min(b.level for b in higher)
            above[a.area_id] = sorted(
                b.area_id for b in higher if _touch(b.level, floor)
            )
        else:
            above[a.area_id] = []
    return beside, above


def outside_faces(room: Footprint, rooms: Sequence[Footprint]) -> dict[str, float]:
    """The length, in metres, of each of the room's faces (N, E, S or W) that no
    other room on its floor shares. A face with none outside is left out."""
    covered = {"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}
    for b in rooms:
        if b.area_id == room.area_id or not _touch(b.level, room.level):
            continue
        if _touch(b.north, room.y):
            covered["S"] += _overlap(room.x, room.east, b.x, b.east)
        if _touch(b.y, room.north):
            covered["N"] += _overlap(room.x, room.east, b.x, b.east)
        if _touch(b.east, room.x):
            covered["W"] += _overlap(room.y, room.north, b.y, b.north)
        if _touch(b.x, room.east):
            covered["E"] += _overlap(room.y, room.north, b.y, b.north)
    edges = {"N": room.width, "E": room.depth, "S": room.width, "W": room.depth}
    exposed = {face: max(0.0, edges[face] - covered[face]) for face in edges}
    return {face: length for face, length in exposed.items() if length > TOLERANCE}
