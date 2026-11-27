# Copyright (c) 2026 MinchinWeb
"""Fit rooms together into a house, from what is known about them.

Standard library only, and nothing of Home Assistant or the drawings: rooms
come in as sizes, links and outside walls, and go out as rectangles.

A floor's rooms are the leaves of a slicing tree: a rectangle cut in two,
each half cut again, down to one room a piece. The rectangle is as big as the
rooms' floor areas together, and each cut shares it out by area, so the rooms
tile it with no gaps and each keeps its area. A room with no width or depth
takes the shape of its piece; a room with both keeps them, and its piece is
made at least that big. Empty pieces (*voids*) let the house be an L or a T,
or leave room for something already there. A void with rooms all round it is
a *hole*: space no room was given, such as a hallway. Two linked rooms that
both open on to the same hole count as linked, and a face on a hole is not on
the outside.

Which tree is best is searched for: the rooms are added one at a time where
they fit best, and the result is then improved a step at a time (a room moved,
two swapped, a cut turned), with a few random steps (from a fixed seed, so the
same house always gives the same layout) to get out of a dead end.

Not every house is a slicing tree (four rooms round a fifth, a pinwheel, is
not), and a room that keeps its size is put where a cut leaves it, not where
it is built. So the rooms are also put down one at a time in places of their
own (``_Fit._by_place``): each against a room it is linked to, its sides on
the lines of what is there, and a room with outside walls where they are
outside the footprint, so the corner rooms go in the footprint's corners.
Whichever of the two layouts costs less is kept. A layout costs more for:

* linked rooms that do not share a wall (or share the wrong face);
* an outside wall with another room against it, or shorter than its length,
  or with the footprint beyond it;
* a face with no outside wall that is left on the outside;
* rooms touching that are not linked (when both have links to other rooms);
* long thin rooms, and a long thin house;
* voids, by their size;
* a room not over the room it is above, or outside the footprint under it
  (the building outline, when there is one);
* footprint with no room over it, and a side of the floor that is not on a
  side of the footprint (but for a side under a roof, with no wall there);
* a room under a ridge that is not where the roofs are as high over both its
  sides.

Floors are fitted one at a time, starting with the biggest; the others are
then free to slide over it to where their rooms sit above the ones below,
their sides on its sides. A floor much smaller than the building outline (or
than the floor it goes over) has floor no room was given: it keeps the
outline's size, and the rooms go round a hole.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import random

Rect = tuple[float, float, float, float]  # west, south, east, north (metres)

N, E, S, W = 0, 1, 2, 3
FACE_INDEX = {"N": N, "E": E, "S": S, "W": W}
_OPPOSITE = (S, W, N, E)


def _flip(face: int | None) -> int | None:
    return None if face is None else _OPPOSITE[face]


TOL = 0.05  # m: edges this close are the same edge
TRUE = 0.3  # m: a floor's side this close to its footprint's is put on it
NEAR = 0.6  # m: a room this close to a face covers it
SHARE = 0.8  # m: linked rooms share at least this much wall (a doorway)
MAX_VOIDS = 3
BEAM = 6  # layouts kept while the rooms are added one at a time
TRIES = 2200  # layouts tried for each room (and void) on a floor
TRIES_MOST = 24000
TIDY = 800  # tries kept back for the last improving
TRIES_LEAST = {1: 400, 2: 2000, 3: 6000}  # for a floor of so few; 12000 for more
HEAT, COOL = 2.0, 0.01  # the search's first heat, and how far it falls
HEAT_HOT = 16.0  # a small floor is searched three times more, from this heat
SMALL = 8  # rooms and voids: a floor of no more is small
SOFT = 0.1  # how much a wrong size costs when the search starts (see ``stiff``)
SEED = 20261113

# What each fault costs. A link that is not met costs about W_LINK; lengths
# are counted against the side of a square as big as the floor, and areas
# against the floor's area, so a big house costs the same as a small one.
W_LINK = 10.0
W_FACE = 4.0  # linked, but not on the face the internal wall names
WING_LINK = 3.0  # how many links a wing apart from its room (or off its face) is
W_WALL = 6.0  # an outside wall that is covered, or too short
W_FULL = 1.5  # an outside wall with no length, partly covered
W_OUT = 6.0  # an outside wall with the footprint on the far side of it
W_BARE = 2.0  # a face with no outside wall, on the outside
W_EAVE = 0.5  # a face under a roof's eave, covered
W_STRAY = 1.0  # rooms touching that are not linked
W_DISTORT = 60.0  # a room drawn bigger or smaller than its floor area
W_ASPECT = 3.0
W_SQUARE = 0.05
W_VOID = 5.0
W_HOLE = 1.0  # a hole: a void with rooms all round it
W_ACROSS = 1.0  # linked across a hole, not by a shared wall
W_ENVELOPE = 2.0
W_OVERLAP = 60.0
W_STACK = 6.0
W_SUPPORT = 15.0
W_FLUSH = 6.0  # a side of the floor that is not on a line of its footprint
W_COVER = 6.0  # footprint with no room over it (nor a hole, up to HALLS)
W_RIDGE = 30.0  # a room under a ridge, off it (by the side of the floor's square)

# the face of a room that each side of a rectangle is on: west, south, east, north
SIDE_FACE = (W, S, E, N)

FLUSH_REACH = 1.0  # m: a side this far from a line costs all of W_FLUSH
# m: how far a floor's outside walls may be in from those of the floor it is
# fitted to, at no cost: a basement's foundation walls are thicker
STEP_IN = 0.3
JOG = 0.75  # m: corners of an outline this close are on one line
HALLS = 0.4  # how much of a floor may be holes (halls no room was given)
# what a layout of only some of a floor's rooms is not judged on: how it sits
# over its footprint, which it cannot yet fill (rooms put down in their places
# are judged on whether they are over it)
PARTIAL_LEFT_OUT = ("support", "flush", "cover")
PLACING_LEFT_OUT = ("flush", "cover")
PLACE_BEAM = 12  # layouts kept while the rooms are put down one at a time
PLACE_TRIES = 6000  # layouts tried while the rooms put down are moved
# m: how far rooms put down may overlap, for sizes typed a little big, or
# rooms open to each other with no wall between
SLACK = 0.15
SIZED_SHARE = 4  # the tree's tries are cut to this share for rooms all sized
FILL = 0.85  # the least of a building outline's area that is floor (not walls)

ASPECT = 1.8  # a room may be this much longer than wide before it costs
ASPECT_LONG = 5.0  # the same for a hallway or stairs
NARROW = 1.2  # m: a room narrower than this costs


@dataclass(frozen=True)
class Room:
    """A room to place.

    Attributes:
        key: Its name in the result.
        area: Its floor area in m².
        size: Its width and depth, when both are known; the room keeps them.
        walls: Its outside walls as ``(face, length)``; the length is 0 when
            it is not known, for a wall that runs the whole face.
        eaves: The faces a roof comes down to.
        long: A hallway or stairs, which may be long and thin.
        ridge: For a room under both roofs of a ridge, ``(axis, share)``
            for each: ``axis`` 0 when the roofs face west and east (the room
            sits across the floor's width), 1 for south and north. The room,
            with its wings, goes where the roofs are as high on both sides of
            it: ``share`` of
            the space beside it, between the walls the roofs come down to (see
            ``Floor.under``), is on its west (or south) side; a half when the
            pitches are the same, so it is under the ridge.
    """

    key: str
    area: float
    size: tuple[float, float] | None = None
    walls: tuple[tuple[str, float], ...] = ()
    eaves: frozenset[str] = frozenset()
    long: bool = False
    ridge: tuple[tuple[int, float], ...] = ()


@dataclass
class Floor:
    """One floor to fit.

    Attributes:
        rooms: The rooms to place.
        fixed: Rooms on this floor that already have a place.
        links: Rooms that share a wall, as ``(a, b, face)``: ``face`` is the
            face of ``a`` that ``b`` is on, or None for any.
        stack: ``(room, rectangle)`` for each placed room on another floor
            that the room is above or below.
        support: The footprint the rooms should stay over.
        free: Whether the floor may slide (it has something to line up with);
            otherwise its south-west corner is at 0, 0.
        width: A first guess of how wide the floor is.
        voids: The areas of the voids to start with.
        wings: For an L-shaped room, its second rectangle (among ``rooms`` or
            ``fixed``) by key, with the key of the room it is part of. A room
            against a wing is against its room. A room may have two; the
            link with a face that puts a wing against its room (or against
            the room's other wing, for a room stepping out twice) says where
            it goes.
        step_in: How far in from the footprint's sides its outside walls may
            be (see ``STEP_IN``): an outside wall is judged by the footprint
            from that far out, and the rooms are also tried that far in.
        under: The walls the roofs of its rooms' ridges come down to: the
            rectangle round the rooms of the floor it is fitted to that have
            no roof of their own (see ``Room.ridge``).
    """

    rooms: list[Room]
    fixed: dict[str, Rect] = field(default_factory=dict)
    links: list[tuple[str, str, str | None]] = field(default_factory=list)
    stack: list[tuple[str, Rect]] = field(default_factory=list)
    support: list[Rect] = field(default_factory=list)
    free: bool = False
    width: float | None = None
    voids: list[float] = field(default_factory=list)
    wings: dict[str, str] = field(default_factory=dict)
    step_in: float = 0.0
    under: Rect | None = None


@dataclass
class _State:
    """One layout being tried."""

    tree: object  # a leaf's number, or (cut, first, second)
    x: float
    y: float
    width: float
    voids: tuple[float, ...]
    anchors: tuple[tuple[int, int], ...]  # each room's corner of its piece


@dataclass(frozen=True)
class _Spots:
    """A layout as each room's own rectangle (None for one not put down yet),
    for the search by place (see ``_Fit._by_place``)."""

    rects: tuple


def _overlap(a: Rect, b: Rect) -> float:
    """The area two rectangles share."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    d = min(a[3], b[3]) - max(a[1], b[1])
    return w * d if w > 0 and d > 0 else 0.0


def _into(a: Rect, b: Rect) -> float:
    """How far two rectangles overlap: the narrower way across what they share
    (0 when they do not overlap)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    d = min(a[3], b[3]) - max(a[1], b[1])
    return min(w, d) if w > 0 and d > 0 else 0.0


def _apart(a: Rect, b: Rect) -> float:
    """How far apart two rectangles are, east-west plus north-south."""
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return dx + dy


def _on_edge(cell: Rect, envelope: Rect) -> bool:
    """Whether a piece is on the edge of the floor's rectangle."""
    return any(abs(cell[k] - envelope[k]) < TOL for k in range(4))


def linked_across(a: Rect, b: Rect, holes: list[Rect], tol: float = TOL) -> bool:
    """Whether two rooms both open on to one of the holes (``tol`` apart at
    most: a wall's thickness, for rooms measured inside)."""
    for hole in holes:
        _, pairs = _contacts([hole, a, b], tol)
        if (0, 1) in pairs and (0, 2) in pairs:
            return True
    return False


def _contacts(rects: list, tol: float = TOL, into: float | None = None):
    """Which rectangles are side by side: for each one, the stretches of its
    faces that others cover (from up to ``NEAR`` away, so a sliver of a gap
    does not make an outside wall), and for each pair that touches (no more
    than ``tol`` apart, or overlapping by no more than ``into``, which is
    ``tol`` unless given), the face of the first and the length they share."""
    into = tol if into is None else into
    faces = [([], [], [], []) for _ in rects]
    pairs: dict[tuple[int, int], tuple[int, float]] = {}
    for i, first in enumerate(rects):
        if first is None:  # not placed yet
            continue
        ax0, ay0, ax1, ay1 = first
        for j in range(i + 1, len(rects)):
            if rects[j] is None:
                continue
            bx0, by0, bx1, by1 = rects[j]
            lo, hi = max(ay0, by0), min(ay1, by1)
            # side by side east and west only if they share more than a
            # sliver north and south: rooms one over the other that overlap
            # by a hair are still one over the other
            if hi - lo > into:
                gap = bx0 - ax1
                side = E
                if gap < -into:
                    gap, side = ax0 - bx1, W
            else:
                lo, hi = max(ax0, bx0), min(ax1, bx1)
                if hi - lo <= 1e-6:
                    continue
                gap = by0 - ay1
                side = N
                if gap < -into:
                    gap, side = ay0 - by1, S
            if gap < -into or gap > NEAR:
                continue
            faces[i][side].append((lo, hi))
            faces[j][_OPPOSITE[side]].append((lo, hi))
            if gap < tol:
                pairs[(i, j)] = (side, hi - lo)
    return faces, pairs


def _outer_lines(rects: list[Rect]) -> tuple[list[float], ...]:
    """Where the outside of some rectangles is: the lines its west, south,
    east and north sides are on (a side with another rectangle all along it
    is not on the outside)."""
    lines: tuple[list[float], ...] = ([], [], [], [])
    faces, _ = _contacts(rects)
    for rect, covered in zip(rects, faces, strict=True):
        for face, k in ((W, 0), (S, 1), (E, 2), (N, 3)):
            span = rect[2] - rect[0] if face in (N, S) else rect[3] - rect[1]
            if sum(hi - lo for lo, hi in covered[face]) < span - TOL:
                lines[k].append(rect[k])
    return lines


# --- the tree -------------------------------------------------------------


def _leaves(tree, path=()):
    """Each leaf's path from the root."""
    if isinstance(tree, int):
        yield path
    else:
        yield from _leaves(tree[1], (*path, 1))
        yield from _leaves(tree[2], (*path, 2))


def _cuts(tree, path=()):
    """Each cut's path from the root."""
    if not isinstance(tree, int):
        yield path
        yield from _cuts(tree[1], (*path, 1))
        yield from _cuts(tree[2], (*path, 2))


def _at(tree, path):
    for step in path:
        tree = tree[step]
    return tree


def _put(tree, path, new):
    """The tree with the part at ``path`` replaced."""
    if not path:
        return new
    parts = list(tree)
    parts[path[0]] = _put(tree[path[0]], path[1:], new)
    return tuple(parts)


def _without(tree, path):
    """The tree with the leaf at ``path`` taken out (its sibling moves up)."""
    sibling = _at(tree, (*path[:-1], 3 - path[-1]))
    return _put(tree, path[:-1], sibling)


def _renumber(tree, gone: int):
    """The tree after leaf ``gone`` is removed: later leaves move down one."""
    if isinstance(tree, int):
        return tree - 1 if tree > gone else tree
    return (tree[0], _renumber(tree[1], gone), _renumber(tree[2], gone))


def _first_tree(order: list[int], cut: int = 0):
    """A balanced tree over the leaves, the cuts turning at each level."""
    if len(order) == 1:
        return order[0]
    half = len(order) // 2
    return (
        cut,
        _first_tree(order[:half], 1 - cut),
        _first_tree(order[half:], 1 - cut),
    )


# --- one floor ------------------------------------------------------------


class _Fit:
    """A floor's rooms, and what a layout of them costs."""

    def __init__(self, floor: Floor) -> None:
        self.rooms = floor.rooms
        self.n = len(floor.rooms)
        self.fixed = list(floor.fixed.values())
        keys = [r.key for r in floor.rooms] + list(floor.fixed)
        index = {key: i for i, key in enumerate(keys)}
        self.total = sum(r.area for r in floor.rooms) or 1.0
        self.scale = math.sqrt(self.total)
        self.links: list[tuple[int, int, int | None]] = []
        self.linked: set[tuple[int, int]] = set()
        for a, b, face in floor.links:
            if a not in index or b not in index or a == b:
                continue
            i, j = index[a], index[b]
            want = FACE_INDEX.get(face or "")
            if i > j:
                i, j = j, i
                want = None if want is None else _OPPOSITE[want]
            if i >= self.n:  # both already placed: nothing to move
                continue
            if (i, j) in self.linked:
                if want is not None:
                    self.links = [
                        (p, q, want if (p, q) == (i, j) else w)
                        for p, q, w in self.links
                    ]
                continue
            self.linked.add((i, j))
            self.links.append((i, j, want))
        # each room with its wings: a link is met by any of them
        self.whole: dict[int, list[int]] = {}
        self.main: dict[int, int] = {}  # each wing's room
        for wing, room in floor.wings.items():
            if wing in index and room in index:
                self.whole.setdefault(index[room], [index[room]]).append(index[wing])
                self.main[index[wing]] = index[room]
        # the part of its room each wing is against: the room, or (a room
        # stepping out twice) its other wing, by the link that puts it there
        self.base: dict[int, int] = dict(self.main)
        for a, b, face in floor.links:
            room = floor.wings.get(b)
            if (
                face
                and a != b
                and room is not None
                and floor.wings.get(a) == room
                and a in index
                and b in index
            ):
                self.base[index[b]] = index[a]
        self.has_links = {i for pair in self.linked for i in pair}
        self.has_links |= {w for w, room in self.main.items() if room in self.has_links}
        self.walls: list[dict[int, float]] = []
        self.eaves: list[set[int]] = []
        self.mins: list[tuple[float, float]] = []
        for room in floor.rooms:
            walls: dict[int, float] = {}
            whole: set[int] = set()
            for face, length in room.walls:
                f = FACE_INDEX[face]
                if length <= 0:
                    whole.add(f)
                walls[f] = walls.get(f, 0.0) + max(length, 0.0)
            for f in whole:
                walls[f] = 0.0
            self.walls.append(walls)
            self.eaves.append({FACE_INDEX[f] for f in room.eaves})
            # a room with no size takes its piece's shape: its outside walls'
            # lengths are met by what a layout costs, not by a least size
            self.mins.append(room.size or (0.0, 0.0))
        # each room's faces with a roof down to them and no outside wall: not
        # over a wall of the floor below (a wing is under its room's roofs)
        self.roofed = [
            eaves - set(walls)
            for eaves, walls in zip(self.eaves, self.walls, strict=True)
        ]
        self.ridges = [room.ridge for room in floor.rooms]
        self.under = floor.under if any(self.ridges) else None
        index_of = {r.key: i for i, r in enumerate(floor.rooms)}
        self.stack = [(index_of[k], rect) for k, rect in floor.stack if k in index_of]
        self.support = floor.support
        self.step_in = floor.step_in
        self.free = floor.free
        others = [*self.fixed, *(r for _, r in self.stack), *self.support]
        self.xs = sorted({r[0] for r in others} | {r[2] for r in others})
        self.ys = sorted({r[1] for r in others} | {r[3] for r in others})
        self.max_voids = min(MAX_VOIDS + len(self.fixed), 5)
        self.holes: list[Rect] = []  # the holes in the layout ``solve`` found
        self.middle = None  # of the footprint, for a floor that may slide
        self.lines = _outer_lines(self.support)
        self.footprint = sum((r[2] - r[0]) * (r[3] - r[1]) for r in self.support)
        if self.support:
            self.middle = (
                (min(r[0] for r in self.support) + max(r[2] for r in self.support)) / 2,
                (min(r[1] for r in self.support) + max(r[3] for r in self.support)) / 2,
            )
        # How much a room of the wrong size costs, against its full cost. The
        # search starts with it low, so that a layout can pass through wrong
        # sizes on its way to a better one, and ends with it whole.
        self.stiff = 1.0
        # What a layout of only part of the floor (rooms still to come) is not
        # judged on: see ``_build`` and ``_by_place``.
        self.left_out: tuple[str, ...] = ()
        self._footprint_of: dict[Rect, float] = {}  # see ``_over``
        # for the search by place: the rooms each room may be against, with
        # the face of that room it is on when a link names one
        self.against: list[list[tuple[int, int | None]]] = [[] for _ in range(self.n)]
        for a, b, want in self.links:
            for i, j, face in ((b, a, want), (a, b, _flip(want))):
                for p in self.whole.get(i, (i,)):
                    if p >= self.n:
                        continue
                    for q in self.whole.get(j, (j,)):
                        exact = face if (p, q) == (i, j) else None
                        if q != p and (q, exact) not in self.against[p]:
                            self.against[p].append((q, exact))

    # the layout a state stands for

    def _measure(self, tree, areas):
        """Each part of the tree with its area and its least width and depth."""
        if isinstance(tree, int):
            if tree < self.n:
                wide, deep = self.mins[tree]
                return (areas[tree], wide, deep, tree)
            return (areas[tree], 0.0, 0.0, tree)
        a = self._measure(tree[1], areas)
        b = self._measure(tree[2], areas)
        if tree[0] == 0:  # side by side, west then east
            return (a[0] + b[0], a[1] + b[1], max(a[2], b[2]), 0, a, b)
        return (a[0] + b[0], max(a[1], b[1]), a[2] + b[2], 1, a, b)

    def _split(self, part, x0, y0, x1, y1, cells) -> None:
        """Share a rectangle out among a part of the tree, by area."""
        if len(part) == 4:
            cells[part[3]] = (x0, y0, x1, y1)
            return
        first, second = part[4], part[5]
        axis = part[3]  # 0: cut across the width; 1: across the depth
        span = (x1 - x0) if axis == 0 else (y1 - y0)
        low, high = first[1 + axis], span - second[1 + axis]
        if low > high:  # too small for both: share the shortfall
            need = first[1 + axis] + second[1 + axis]
            share = span * first[1 + axis] / need if need > 0 else span / 2
        else:
            share = min(max(span * first[0] / part[0], low), high)
        if axis == 0:
            self._split(first, x0, y0, x0 + share, y1, cells)
            self._split(second, x0 + share, y0, x1, y1, cells)
        else:
            self._split(first, x0, y0, x1, y0 + share, cells)
            self._split(second, x0, y0 + share, x1, y1, cells)

    def layout(self, state: _State | _Spots):
        """Each room's rectangle, each leaf's piece, and the whole rectangle."""
        if isinstance(state, _Spots):  # each room is its own piece
            rects = list(state.rects)
            there = [r for r in rects if r is not None] or [(0.0, 0.0, 0.0, 0.0)]
            envelope = (
                min(r[0] for r in there),
                min(r[1] for r in there),
                max(r[2] for r in there),
                max(r[3] for r in there),
            )
            return rects, list(rects), envelope
        areas = [
            r.size[0] * r.size[1] if r.size else r.area for r in self.rooms
        ] + list(state.voids)
        part = self._measure(state.tree, areas)
        width = max(state.width, part[1], 0.1)
        depth = max(part[0] / width, part[2])
        cells: list = [None] * len(areas)
        self._split(part, 0.0, 0.0, width, depth, cells)
        rects: list = []
        for i, room in enumerate(self.rooms):
            cell = cells[i]
            if room.size is None or cell is None:
                rects.append(cell)
                continue
            wide, deep = room.size
            east, north = state.anchors[i]
            x = cell[2] - wide if east else cell[0]
            y = cell[3] - deep if north else cell[1]
            rects.append((x, y, x + wide, y + deep))
        # A floor that may slide is set where its rooms are, on average, over
        # the rooms they go with (else in the middle of its footprint), so
        # every tree is tried in a good place; ``x`` and ``y`` move it on.
        dx, dy = state.x, state.y
        if self.free and self.stack:
            count = 0
            for i, other in self.stack:
                rect = rects[i]
                if rect is not None:
                    dx += (other[0] + other[2] - rect[0] - rect[2]) / 2
                    dy += (other[1] + other[3] - rect[1] - rect[3]) / 2
                    count += 1
            if count:
                dx = state.x + (dx - state.x) / count
                dy = state.y + (dy - state.y) / count
        elif self.free and self.middle is not None:
            dx += self.middle[0] - width / 2
            dy += self.middle[1] - depth / 2
        if self.free and self.support:
            # and from there on to the nearest side of the footprint
            there = [r for r in rects if r is not None]
            for axis in (0, 1):
                low = min(r[axis] for r in there) + (dy if axis else dx)
                high = max(r[axis + 2] for r in there) + (dy if axis else dx)
                moves = []
                if not self._roofed_side(rects, axis):
                    moves += [line - low for line in self.lines[axis]]
                if not self._roofed_side(rects, axis + 2):
                    moves += [line - high for line in self.lines[axis + 2]]
                move = min(moves, key=abs, default=0.0)
                if abs(move) <= FLUSH_REACH:
                    if axis:
                        dy += move
                    else:
                        dx += move
        if dx or dy:
            rects = [r and (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy) for r in rects]
            cells = [c and (c[0] + dx, c[1] + dy, c[2] + dx, c[3] + dy) for c in cells]
        return rects, cells, (dx, dy, dx + width, dy + depth)

    def cost(self, state: _State | _Spots, detail: dict | None = None) -> float:
        """What a layout costs (see the module's notes). ``detail`` is filled
        with the cost by fault, for looking into a layout."""
        rects, cells, envelope = self.layout(state)
        n, scale, total = self.n, self.scale, self.total
        # a hole is like a room to the rooms round it: it covers their faces,
        # and two rooms on it can be linked across it
        holes = [
            cell
            for cell in cells[n:]
            if cell is not None and not _on_edge(cell, envelope)
        ]
        every = rects + self.fixed + holes
        first_hole = len(every) - len(holes)
        # rooms put down in places of their own touch though they overlap a
        # little, as sizes typed a little big make them
        faces, pairs = _contacts(
            every, TOL, SLACK if isinstance(state, _Spots) else TOL
        )
        parts = dict.fromkeys(
            (
                "links",
                "walls",
                "bare",
                "stray",
                "shape",
                "voids",
                "envelope",
                "overlap",
                "stack",
                "support",
                "flush",
                "cover",
                "ridge",
            ),
            0.0,
        )
        for i, j, want in self.links:
            a, b = every[i], every[j]
            if a is None or b is None:
                continue
            need = max(
                1e-6,
                min(
                    SHARE,
                    0.6 * min(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]),
                ),
            )
            got = pairs.get((i, j))
            mine, yours = self.whole.get(i, (i,)), self.whole.get(j, (j,))
            if len(mine) > 1 or len(yours) > 1:
                # an L-shaped room: the longest wall any of its parts shares
                apart = _apart(a, b)
                for p in mine:
                    for q in yours:
                        if p == q or every[p] is None or every[q] is None:
                            continue
                        apart = min(apart, _apart(every[p], every[q]))
                        if p < q:
                            other = pairs.get((p, q))
                        else:
                            other = pairs.get((q, p))
                            if other is not None:
                                other = (_OPPOSITE[other[0]], other[1])
                        if other is not None and (got is None or other[1] > got[1]):
                            got = other
            else:
                apart = _apart(a, b)
            # a wing apart from its room is no L, and costs the more
            wing = self.base.get(j) == i or self.base.get(i) == j
            weight = WING_LINK if wing else 1.0
            if got is not None and got[1] >= need:
                if want is not None and got[0] != want:
                    parts["links"] += W_FACE * weight
            elif not wing and any(
                any(pairs.get((p, h), (0, 0.0))[1] >= need for p in mine)
                and any(pairs.get((q, h), (0, 0.0))[1] >= need for q in yours)
                for h in range(first_hole, len(every))
            ):
                parts["links"] += W_ACROSS
            elif got is not None:
                parts["links"] += W_LINK * weight * (1.0 - 0.5 * got[1] / need)
            else:
                parts["links"] += W_LINK * weight * (1.0 + apart / scale)
        for i in range(n):
            if rects[i] is None:
                continue
            x0, y0, x1, y1 = rects[i]
            walls, eaves = self.walls[i], self.eaves[i]
            for f, need in walls.items() if self.support else ():
                parts["walls"] += W_OUT * self._kept_in(rects[i], f, need)
            for f in (N, E, S, W):
                span = max((x1 - x0) if f in (N, S) else (y1 - y0), 1e-6)
                covered = min(span, sum(hi - lo for lo, hi in faces[i][f]))
                bare = span - covered
                need = walls.get(f)
                if need is None:
                    if f in eaves:
                        parts["walls"] += W_EAVE * covered / span
                    else:
                        parts["bare"] += W_BARE * bare / scale
                elif need > 0:
                    if self.rooms[i].size:  # it cannot grow to fit its wall
                        need = min(need, span)
                    if faces[i][f]:  # the longest stretch with nothing against it
                        start = x0 if f in (N, S) else y0
                        at, bare = start, 0.0
                        for lo, hi in sorted(faces[i][f]):
                            bare = max(bare, lo - at)
                            at = max(at, hi)
                        bare = max(bare, start + span - at)
                    # a third of a wall's length covered is as bad as all of it
                    short = max(0.0, need - bare) / need
                    parts["walls"] += W_WALL * min(1.0, 3.0 * short)
                else:
                    least = min(span, 1.0)
                    parts["walls"] += (
                        W_WALL * max(0.0, least - bare) / least
                        + W_FULL * covered / span
                    )
        for (i, j), (_, length) in pairs.items():
            # only between rooms that have links: one with none says nothing
            p, q = sorted((self.main.get(i, i), self.main.get(j, j)))
            if (
                i < n
                and p != q
                and (p, q) not in self.linked
                and i in self.has_links
                and j in self.has_links
            ):
                parts["stray"] += W_STRAY * length / scale
        for i, room in enumerate(self.rooms):
            if cells[i] is None:
                continue
            cx0, cy0, cx1, cy1 = cells[i]
            wide, deep = max(cx1 - cx0, 1e-6), max(cy1 - cy0, 1e-6)
            if room.size:
                short = max(0.0, room.size[0] - wide) + max(0.0, room.size[1] - deep)
                spare = max(0.0, wide * deep - room.size[0] * room.size[1])
                parts["shape"] += (
                    self.stiff * W_OVERLAP * short / scale + W_VOID * spare / total
                )
                continue
            parts["shape"] += (
                self.stiff * W_DISTORT * abs(wide * deep - room.area) / room.area
            )
            aspect = max(wide / deep, deep / wide)
            parts["shape"] += W_SQUARE * (aspect - 1.0)  # all else equal, squarer
            limit = ASPECT_LONG if room.long else ASPECT
            if aspect > limit:
                parts["shape"] += W_ASPECT * (aspect - limit) ** 2
            narrow = min(NARROW, 0.75 * math.sqrt(room.area))
            if min(wide, deep) < narrow:
                parts["shape"] += 4 * W_ASPECT * (narrow - min(wide, deep)) / narrow
        for cell in cells[n:]:
            if cell is None:
                continue
            empty = (cell[2] - cell[0]) * (cell[3] - cell[1])
            empty -= sum(_overlap(cell, other) for other in self.fixed)
            parts["voids"] += W_VOID * max(0.0, empty) / total
            if not _on_edge(cell, envelope):
                parts["voids"] += W_HOLE
        wide = max(envelope[2] - envelope[0], 1e-6)
        deep = max(envelope[3] - envelope[1], 1e-6)
        aspect = max(wide / deep, deep / wide)
        if aspect > 2.0:
            parts["envelope"] += W_ENVELOPE * (aspect - 2.0) ** 2
        placed = [rect for rect in rects if rect is not None]
        for other in self.fixed:
            for rect in placed:
                parts["overlap"] += W_OVERLAP * _overlap(rect, other) / total
        if isinstance(state, _Spots):  # rooms put down may overlap a little
            for k, rect in enumerate(placed):
                for other in placed[k + 1 :]:
                    parts["overlap"] += W_OVERLAP * _overlap(rect, other) / total
                    # more is one room in another: as bad as a link not met,
                    # and up to three, the further in it is
                    into = _into(rect, other) - SLACK
                    if into > 0:
                        parts["overlap"] += W_LINK * min(3.0, into / SLACK)
        for i, other in self.stack:
            rect = rects[i]
            if rect is None:
                continue
            least = 1e-9 + 0.5 * min(
                (rect[2] - rect[0]) * (rect[3] - rect[1]),
                (other[2] - other[0]) * (other[3] - other[1]),
            )
            over = _overlap(rect, other)
            if over < least:
                parts["stack"] += W_STACK * (1.0 - over / least)
                if over <= 0:
                    parts["stack"] += W_STACK * _apart(rect, other) / scale
        if self.support:
            cover = 0.0
            for rect in placed:
                area = (rect[2] - rect[0]) * (rect[3] - rect[1])
                held = self._over(rect)
                parts["support"] += W_SUPPORT * max(0.0, area - held) / total
                cover += held
            # a hole is floor too (a hallway), but only so much of a floor
            halls = sum(self._over(hole) for hole in holes)
            cover += min(halls, HALLS * total)
            parts["cover"] += W_COVER * max(0.0, self.footprint - cover) / total
            # each side of the floor is on a line of its footprint, but for a
            # side under a roof
            for k in range(4):
                if self._roofed_side(rects, k):
                    continue
                side = (min if k < 2 else max)(rect[k] for rect in placed)
                off = min(abs(side - line) for line in self.lines[k])
                parts["flush"] += W_FLUSH * min(1.0, off / FLUSH_REACH)
        if self.under is not None:  # a room under a ridge, where it goes under it
            for i, ridges in enumerate(self.ridges):
                for axis, share in ridges:
                    span = self._extent(rects, i, axis)
                    if span is not None:
                        where = self._under_ridge(axis, share, span[1] - span[0])
                        parts["ridge"] += W_RIDGE * abs(span[0] - where) / scale
        if detail is not None:
            detail.update(parts)
        if self.left_out:
            return sum(v for k, v in parts.items() if k not in self.left_out)
        return sum(parts.values())

    # the search

    def _change(self, state: _State, rng: random.Random) -> _State | None:
        """A layout one step away, or None when the step cannot be made."""
        tree, voids = state.tree, state.voids
        count = self.n + len(voids)
        roll = rng.random()
        if roll < 0.06 and count > 1:  # the whole floor the other way round
            how = rng.randrange(3)
            if how == 2:
                return self._turned(state, _mirror(tree, 2))
            return _replace(state, tree=_mirror(tree, how))
        if roll < 0.62 and count > 1:
            kind = rng.randrange(4)
            if kind == 0:  # swap two leaves
                a, b = rng.sample(list(_leaves(tree)), 2)
                first, second = _at(tree, a), _at(tree, b)
                return _replace(state, tree=_put(_put(tree, a, second), b, first))
            path = rng.choice(list(_cuts(tree)))
            cut = _at(tree, path)
            if kind == 1:  # turn a cut
                new = _put(tree, path, (1 - cut[0], cut[1], cut[2]))
                if not path and rng.random() < 0.5:
                    return self._turned(state, new)
                return _replace(state, tree=new)
            if kind == 2:  # swap a cut's two sides
                return _replace(state, tree=_put(tree, path, (cut[0], cut[2], cut[1])))
            if count < 3:
                return None
            leaf_path = rng.choice(list(_leaves(tree)))
            return _replace(
                state, tree=_graft(_without(tree, leaf_path), _at(tree, leaf_path), rng)
            )
        if roll < 0.80:
            return self._move(state, rng)
        if roll < 0.92:
            return self._void(state, rng)
        rigid = [i for i, room in enumerate(self.rooms) if room.size]
        if not rigid:
            return self._move(state, rng)
        i = rng.choice(rigid)
        east, north = state.anchors[i]
        if rng.random() < 0.5:
            east = 1 - east
        else:
            north = 1 - north
        anchors = list(state.anchors)
        anchors[i] = (east, north)
        return _replace(state, anchors=tuple(anchors))

    def _turned(self, state: _State, tree) -> _State:
        """A layout with a new tree, as wide as it was deep."""
        _, _, envelope = self.layout(state)
        return _replace(state, tree=tree, width=envelope[3] - envelope[1])

    def _move(self, state: _State, rng: random.Random) -> _State | None:
        """Slide the floor, or make it wider or narrower."""
        kind = rng.randrange(4 if self.free else 2)
        if kind == 0:
            return _replace(state, width=state.width * math.exp(rng.gauss(0, 0.12)))
        if kind == 1:  # as wide as something it lines up with
            if not self.xs:
                return _replace(state, width=state.width * math.exp(rng.gauss(0, 0.04)))
            width = rng.choice(self.xs) - state.x
            return _replace(state, width=width) if width > 0.5 else None
        if kind == 2:
            return _replace(
                state,
                x=state.x + rng.gauss(0, 0.1 * self.scale),
                y=state.y + rng.gauss(0, 0.1 * self.scale),
            )
        _, _, envelope = self.layout(state)
        if rng.random() < 0.5 and self.xs:
            edge = rng.choice((envelope[0], envelope[2]))
            return _replace(state, x=state.x + rng.choice(self.xs) - edge)
        if self.ys:
            edge = rng.choice((envelope[1], envelope[3]))
            return _replace(state, y=state.y + rng.choice(self.ys) - edge)
        return None

    def _void(self, state: _State, rng: random.Random) -> _State | None:
        """Add a void, take one out, or change its size."""
        voids = list(state.voids)
        kind = rng.randrange(3)
        if kind == 0 and len(voids) < self.max_voids:
            voids.append(self.total * rng.uniform(0.02, 0.2))
            leaf = self.n + len(voids) - 1
            return _replace(
                state, tree=_graft(state.tree, leaf, rng), voids=tuple(voids)
            )
        if not voids:
            return None
        which = rng.randrange(len(voids))
        if kind == 1:
            leaf = self.n + which
            path = next(p for p in _leaves(state.tree) if _at(state.tree, p) == leaf)
            if not path:
                return None
            del voids[which]
            tree = _renumber(_without(state.tree, path), leaf)
            return _replace(state, tree=tree, voids=tuple(voids))
        voids[which] *= math.exp(rng.gauss(0, 0.3))
        return _replace(state, voids=tuple(voids))

    def _start(self, floor: Floor, rng: random.Random) -> _State:
        """A first layout: the rooms in the order their links are followed."""
        beside: dict[int, list[int]] = {i: [] for i in range(self.n)}
        for i, j, _ in self.links:
            if j < self.n:
                beside[i].append(j)
                beside[j].append(i)
        order: list[int] = []
        for first in sorted(range(self.n), key=lambda i: -len(beside[i])):
            todo = [first]
            while todo:
                i = todo.pop(0)
                if i not in order:
                    order.append(i)
                    todo.extend(beside[i])
        voids = tuple(v for v in floor.voids if v > 0)[: self.max_voids]
        order += [self.n + k for k in range(len(voids))]
        area = self.total + sum(voids)
        width = floor.width or math.sqrt(area * 1.3)
        x = y = 0.0
        if self.support and not self.free:  # at the footprint's corner
            x = min(r[0] for r in self.support)
            y = min(r[1] for r in self.support)
        if self.free and not self.stack and not self.support and self.fixed:
            x = max(r[2] for r in self.fixed)  # beside what is placed
            y = min(r[1] for r in self.fixed)
        anchors = []
        for walls in self.walls:
            anchors.append(
                (
                    1 if E in walls and W not in walls else 0,
                    1 if N in walls and S not in walls else 0,
                )
            )
        return _State(_first_tree(order), x, y, width, voids, tuple(anchors))

    def _near(self, state: _State):
        """Every layout one step from this one: the tree's first, then the
        floor's width and place, its voids, and the rooms' corners."""
        tree = state.tree
        leaves, cuts = list(_leaves(tree)), list(_cuts(tree))
        # as wide as its rooms' sizes need, and as wide as it is deep
        areas = [r.size[0] * r.size[1] if r.size else r.area for r in self.rooms]
        part = self._measure(tree, areas + list(state.voids))
        for width in (part[1], math.sqrt(part[0])):
            if width > 0.5 and abs(width - state.width) > 1e-9:
                yield _replace(state, width=width)
        yield self._turned(state, _mirror(tree, 2))
        for path in cuts:
            cut = _at(tree, path)
            turned = _put(tree, path, (1 - cut[0], cut[1], cut[2]))
            yield _replace(state, tree=turned)
            if not path:
                yield self._turned(state, turned)
            yield _replace(state, tree=_put(tree, path, (cut[0], cut[2], cut[1])))
        for k, a in enumerate(leaves):
            for b in leaves[k + 1 :]:
                first, second = _at(tree, a), _at(tree, b)
                yield _replace(state, tree=_put(_put(tree, a, second), b, first))
        if len(leaves) >= 3:
            for path in leaves:
                rest = _without(tree, path)
                for new in _grafts(rest, _at(tree, path)):
                    yield _replace(state, tree=new)
        for factor in (0.85, 0.94, 1.06, 1.18):
            yield _replace(state, width=state.width * factor)
        for x in self.xs:
            if x - state.x > 0.5:
                yield _replace(state, width=x - state.x)
        if self.free:
            _, _, envelope = self.layout(state)
            for x in self.xs:
                yield _replace(state, x=state.x + x - envelope[0])
                yield _replace(state, x=state.x + x - envelope[2])
            for y in self.ys:
                yield _replace(state, y=state.y + y - envelope[1])
                yield _replace(state, y=state.y + y - envelope[3])
            step = 0.05 * self.scale
            for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                yield _replace(state, x=state.x + dx, y=state.y + dy)
        for which, area in enumerate(state.voids):
            for factor in (0.6, 0.8, 1.25, 1.6):
                voids = list(state.voids)
                voids[which] = area * factor
                yield _replace(state, voids=tuple(voids))
            leaf = self.n + which
            path = next(p for p in leaves if _at(tree, p) == leaf)
            if path:
                voids = list(state.voids)
                del voids[which]
                yield _replace(
                    state,
                    tree=_renumber(_without(tree, path), leaf),
                    voids=tuple(voids),
                )
        # one void bigger and another as much smaller: the floor stays as big
        for which, area in enumerate(state.voids):
            for other in range(len(state.voids)):
                for part in (0.15, 0.4) if other != which else ():
                    voids = list(state.voids)
                    voids[which] -= area * part
                    voids[other] += area * part
                    yield _replace(state, voids=tuple(voids))
        if len(state.voids) < self.max_voids:
            for part in (0.08, 0.25):
                voids = (*state.voids, part * self.total)
                for new in _grafts(tree, self.n + len(state.voids)):
                    yield _replace(state, tree=new, voids=voids)
        for i, room in enumerate(self.rooms):
            if room.size:
                east, north = state.anchors[i]
                for corner in ((1 - east, north), (east, 1 - north)):
                    anchors = list(state.anchors)
                    anchors[i] = corner
                    yield _replace(state, anchors=tuple(anchors))

    def _improve(self, state: _State, cost: float, tries: int):
        """Step to a better layout until none of the layouts one step away is
        better (or the tries run out). Returns the layout, its cost and the
        tries left."""
        better = True
        while better and tries > 0:
            better = False
            for new in self._near(state):
                tries -= 1
                new_cost = self.cost(new)
                if new_cost < cost - 1e-9:
                    state, cost, better = new, new_cost, True
                    break
                if tries <= 0:
                    break
        return state, cost, tries

    def _build(self, start: _State) -> list[_State]:
        """Layouts built a room at a time: each room is tried in every place
        in the layouts so far, and the best few are kept for the next.

        Part of a floor is not yet as big as its footprint, nor in its place
        over it, so it is judged without the footprint (see
        ``PARTIAL_LEFT_OUT``): by its links, outside walls and shapes."""
        self.left_out = PARTIAL_LEFT_OUT
        try:
            return self._build_beam(start)
        finally:
            self.left_out = ()

    def _build_beam(self, start: _State) -> list[_State]:
        order = [_at(start.tree, path) for path in _leaves(start.tree)]
        areas = [r.size[0] * r.size[1] if r.size else r.area for r in self.rooms]
        areas += list(start.voids)
        whole = sum(areas)
        beam = [order[0]]
        done = areas[order[0]]
        for leaf in order[1:]:
            done += areas[leaf]
            # a part of the floor is as wide as its share of the whole
            width = start.width * math.sqrt(done / whole)
            found: dict = {}
            for tree in beam:
                for new in _grafts(tree, leaf):
                    if new not in found:
                        found[new] = self.cost(_replace(start, tree=new, width=width))
            beam = sorted(found, key=found.get)[:BEAM]
        return [_replace(start, tree=tree) for tree in beam]

    def solve(self, floor: Floor, seed: int = SEED) -> dict[str, Rect]:
        """The best layout found, as each room's rectangle.

        The rooms are added one at a time (``_build``), the best layouts are
        improved a step at a time (``_improve``), and then the best is knocked
        a few random steps away and improved again, for as long as the tries
        last, in case a better one is near.
        """
        if not self.n:
            return {}
        rng = random.Random(seed)
        start = self._start(floor, rng)
        leaves = self.n + len(start.voids)
        tries = min(TRIES_MOST, max(TRIES_LEAST.get(leaves, 12000), TRIES * leaves))
        # rooms that all keep their sizes are put down best by place (see
        # ``_by_place``): the tree is only a check on that, and searched less
        sized = all(room.size for room in self.rooms)
        if sized:
            tries //= SIZED_SHARE
        best, best_cost = start, self.cost(start)
        if leaves > 1:
            for state in self._build(start)[:3]:
                state, cost, tries = self._improve(state, self.cost(state), tries)
                if cost < best_cost:
                    best, best_cost = state, cost
        # anneal from there: random steps, a worse one taken less often as the
        # heat falls and the rooms' sizes stiffen; then improve what that found
        keep = tries // 4
        steps = tries - keep
        keep += 2 * TIDY  # the last improving always has this much
        # a small floor with a footprint to line up with is quick, and is
        # searched hot as well: that gets it out of a layout that only a few
        # steps together would better
        hot = self.free and self.support and 1 < leaves <= SMALL and not sized
        heats = [HEAT_HOT] * 3 + [HEAT] if hot else [HEAT]
        found = []
        for first in heats:
            now, now_cost = best, best_cost
            seen, seen_cost = best, best_cost  # the best while annealing
            for step in range(steps):
                done = step / steps
                heat = first * ((COOL * HEAT / first) ** done)
                if step % 64 == 0:
                    self.stiff = SOFT + (1.0 - SOFT) * done
                    now_cost, seen_cost = self.cost(now), self.cost(seen)
                new = self._change(now, rng)
                if new is None:
                    continue
                new_cost = self.cost(new)
                if new_cost <= now_cost or rng.random() < math.exp(
                    (now_cost - new_cost) / heat
                ):
                    now, now_cost = new, new_cost
                    if now_cost < seen_cost:
                        seen, seen_cost = now, now_cost
            found += [seen, now]
        self.stiff = 1.0
        for state in found:
            state, cost, _ = self._improve(state, self.cost(state), keep // 2)
            if cost < best_cost:
                best, best_cost = state, cost
        best = self._tidy(best)
        # and by putting each room down where it fits best: the better of the two
        placed = self._by_place()
        if placed is not None and placed[1] < self.cost(best) - 1e-6:
            best = placed[0]
        self.best = best
        rects, cells, envelope = self.layout(best)
        self.holes = [c for c in cells[self.n :] if not _on_edge(c, envelope)]
        rects = self._trued(rects)
        return {room.key: rect for room, rect in zip(self.rooms, rects, strict=True)}

    def _trued(self, rects: list[Rect]) -> list[Rect]:
        """The rooms with each side of the floor that is all but on a side of
        its footprint put on it: a room with no width or depth typed is
        stretched the last few centimetres."""
        if not self.support:
            return rects
        out = [list(rect) for rect in rects]
        for k in range(4):
            if self._roofed_side(rects, k):
                continue
            side = (min if k < 2 else max)(rect[k] for rect in rects)
            line = min(self.lines[k], key=lambda v: abs(v - side), default=side)
            if not 0 < abs(line - side) <= TRUE:
                continue
            for rect, room in zip(out, self.rooms, strict=True):
                if abs(rect[k] - side) < TOL and not room.size:
                    rect[k] = line
        return [(r[0], r[1], r[2], r[3]) for r in out]

    def _tidy(self, state: _State) -> _State:
        """The layout moved the last few centimetres, so an edge that is all
        but on an edge of what it lines up with is on it."""
        if not self.free:
            return state
        rects, _, _ = self.layout(state)
        dx = dy = 0.0
        for rect in rects:
            for line in self.xs:
                for edge in (rect[0], rect[2]):
                    if not dx and 0 < abs(line - edge) < 2 * TOL:
                        dx = line - edge
            for line in self.ys:
                for edge in (rect[1], rect[3]):
                    if not dy and 0 < abs(line - edge) < 2 * TOL:
                        dy = line - edge
        return _replace(state, x=state.x + dx, y=state.y + dy)

    # the search by place

    def _by_place(self) -> tuple[_Spots, float] | None:
        """The best layout found by putting each room down in a place of its
        own, and its cost; None when there is none.

        A room is put against a room it is linked to that is down already,
        each of its sides lined up with a line of what is there (a room's
        side, the footprint's, a room above or below); a room with outside
        walls goes where those faces are outside the footprint, so the first
        rooms go in its corners. The rooms go down one at a time, the most
        tied to what is down first, and the best few layouts are kept for the
        next (``PLACE_BEAM``). Then the best few are made better
        (``_settle``).

        Rooms that keep their sizes fit this best: a slicing tree (``solve``)
        cannot make every layout, and a room is put down here where it is
        built, not where a cut of the floor leaves it.
        """
        if not self.n:
            return None
        start = (None,) * self.n
        beam, _ = self._put_down(start, self._place_order(start), PLACE_BEAM)
        best: tuple[float, tuple] | None = None
        tries = PLACE_TRIES
        for rects in beam[:3]:
            cost = self.cost(_Spots(rects))
            rects, cost, tries = self._settle(rects, cost, max(tries, PLACE_TRIES // 4))
            if best is None or cost < best[0]:
                best = (cost, rects)
        return (_Spots(best[1]), best[0]) if best else None

    def _put_down(self, start: tuple, order: list[int], width: int):
        """Layouts with the rooms in ``order`` put down one at a time on
        ``start``, each in every place it may go, keeping the best ``width``
        for the next room. Returns them, the best first, and how many layouts
        were tried."""
        beam: list[tuple[float, tuple]] = [(0.0, start)]
        tried = 0
        self.left_out = PLACING_LEFT_OUT
        try:
            for i in order:
                found: dict[tuple, tuple[float, tuple]] = {}
                for _, rects in beam:
                    for rect in self._spots(rects, i):
                        new = (*rects[:i], rect, *rects[i + 1 :])
                        key = _rounded(new)
                        if key not in found:
                            found[key] = (self.cost(_Spots(new)), new)
                tried += len(found)
                beam = sorted(found.values(), key=lambda item: item[0])[:width]
        finally:
            self.left_out = ()
        return [rects for _, rects in beam], tried

    def _place_order(self, rects: tuple) -> list[int]:
        """The rooms not yet down in ``rects``, in the order they are put
        down: each time, the one with the most links to rooms down already,
        counting each outside wall (up to two, a corner) as one, when there is
        a footprint to be outside of; the bigger first when that is even. A
        wing goes down right after its room."""
        down = {i for i, rect in enumerate(rects) if rect is not None}
        down |= set(range(self.n, self.n + len(self.fixed)))
        order: list[int] = []
        todo = [i for i in range(self.n) if i not in down]
        while todo:

            def weight(i: int) -> tuple:
                linked = sum(1 for j, _ in self.against[i] if j in down)
                walls = min(2, len(self.walls[i])) if self.support else 0
                if not down and not self.support:  # the first: the most linked
                    linked = len(self.against[i])
                return (linked + walls, self.rooms[i].area)

            ready = [i for i in todo if self.base.get(i) not in todo]
            wings = [i for i in ready if i in self.base]  # what it is on is down
            i = wings[0] if wings else max(ready or todo, key=weight)
            order.append(i)
            down.add(i)
            todo.remove(i)
        return order

    def _shapes(self, i: int, rects: tuple) -> list[tuple[float, float]]:
        """The widths and depths room ``i`` may take: its own, or for a room
        with only a floor area, a few as big as that (square, longer each way,
        as long as a side of a room it is against)."""
        room = self.rooms[i]
        if room.size:
            return [room.size]
        area = room.area
        side = math.sqrt(area)
        limit = ASPECT_LONG if room.long else ASPECT
        shapes = {(side, side)}
        for stretch in (1.3, limit):
            shapes |= {(side * math.sqrt(stretch), side / math.sqrt(stretch))}
            shapes |= {(side / math.sqrt(stretch), side * math.sqrt(stretch))}
        every = [*rects, *self.fixed]
        for j, _ in self.against[i]:
            other = every[j]
            if other is None:
                continue
            for length in (other[2] - other[0], other[3] - other[1]):
                if (
                    length > 0
                    and max(length, area / length) / min(length, area / length) <= limit
                ):
                    shapes |= {(length, area / length), (area / length, length)}
        return sorted(shapes)

    def _spots(self, rects: tuple, i: int) -> list[Rect]:
        """Where room ``i`` may go, with the rooms in ``rects`` down: against
        a room it is linked to, lined up with the lines of what is there (or
        right over a room it is above or below). With none of those places
        free, at a corner of those lines; then against any room down; at
        last, east of them all.

        None overlaps what is down (by more than ``SLACK``), or is mostly
        off the footprint; a room with outside walls keeps only the places
        where they are outside it, if it has any. A wing is always against
        its room's face: at either end of it, so the two make an L, else
        lined up along it, else at the ends whatever is there."""
        every = [*rects, *self.fixed]
        others = [r for k, r in enumerate(every) if r is not None and k != i]
        xs: set[float] = set()
        ys: set[float] = set()
        for rect in (*others, *self.support, *(r for _, r in self.stack)):
            xs |= {rect[0], rect[2]}
            ys |= {rect[1], rect[3]}
        if self.step_in:  # the footprint's sides, as far in as walls may step
            xs |= {v + self.step_in for v in self.lines[0]}
            xs |= {v - self.step_in for v in self.lines[2]}
            ys |= {v + self.step_in for v in self.lines[1]}
            ys |= {v - self.step_in for v in self.lines[3]}
        own = every[self.base[i]] if i in self.base else None
        if own is not None:  # a wing, what it is on down
            mine = [(own, f) for j, f in self.against[i] if j == self.base[i]]
            tiers: list = [(mine, True), (mine, False)]
        else:
            partners = [
                (every[j], f) for j, f in self.against[i] if every[j] is not None
            ]
            tiers = [(partners, False)]
            if self.support or self.stack:
                tiers.append((None, False))  # a corner of the lines
            tiers.append(([(rect, None) for rect in others], False))
        shapes = self._shapes(i, rects)
        if self.under is not None:  # under its ridge
            for axis, share in self.ridges[i]:
                lines = ys if axis else xs
                lines |= {self._under_ridge(axis, share, s[axis]) for s in shapes}
        first: list[Rect] = []
        for number, (tier, ends) in enumerate(tiers):
            found: set[Rect] = set()
            for wide, deep in shapes:
                if tier is None:
                    for x in {*xs, *(v - wide for v in xs)}:
                        for y in {*ys, *(v - deep for v in ys)}:
                            found.add((x, y, x + wide, y + deep))
                    continue
                if not number:  # right over a room above or below it
                    for k, other in self.stack:
                        if k == i:
                            for x in (other[0], other[2] - wide):
                                for y in (other[1], other[3] - deep):
                                    found.add((x, y, x + wide, y + deep))
                for other, face in tier:
                    for f in (N, E, S, W) if face is None else (face,):
                        if f in (E, W):
                            x = other[2] if f == E else other[0] - wide
                            for y in _along(other[1], other[3], deep, ys, ends):
                                found.add((x, y, x + wide, y + deep))
                        else:
                            y = other[3] if f == N else other[1] - deep
                            for x in _along(other[0], other[2], wide, xs, ends):
                                found.add((x, y, x + wide, y + deep))
            found_list = sorted(found)
            first = first or found_list
            ok = [
                rect
                for rect in found_list
                if not any(_into(rect, other) > SLACK for other in others)
                and self._held(rect) >= 0.5
            ]
            if ok:
                outside = [rect for rect in ok if self._walls_out(rect, i)]
                return outside or ok
        if own is not None and first:
            return first
        wide, deep = shapes[0]
        if not others:
            return [(0.0, 0.0, wide, deep)]
        east = max(r[2] for r in others)
        south = min(r[1] for r in others)
        return [(east, south, east + wide, south + deep)]

    def _held(self, rect: Rect) -> float:
        """How much of a rectangle is over the footprint (all of it, with no
        footprint)."""
        if not self.support:
            return 1.0
        area = max((rect[2] - rect[0]) * (rect[3] - rect[1]), 1e-9)
        return self._over(rect) / area

    def _over(self, rect: Rect) -> float:
        """How much of a rectangle is over the footprint, in m² (kept, as the
        same rectangles come again and again)."""
        held = self._footprint_of.get(rect)
        if held is None:
            held = sum(_overlap(rect, other) for other in self.support)
            if len(self._footprint_of) > 50_000:  # a tree's are seldom the same
                self._footprint_of.clear()
            self._footprint_of[rect] = held
        return held

    def _walls_out(self, rect: Rect, i: int) -> bool:
        """Whether each of room ``i``'s outside walls, with the room at
        ``rect``, is mostly on the outside of the footprint."""
        if not self.support:
            return True
        return all(
            self._kept_in(rect, f, need) <= 0.5 for f, need in self.walls[i].items()
        )

    def _kept_in(self, rect: Rect, f: int, need: float) -> float:
        """How much of an outside wall (``need`` long, or the whole face for
        0) has footprint beyond it, from 0 to 1: the share of a strip
        ``NEAR`` deep outside the face that is footprint, past what of the
        face is not outside. The strip starts ``step_in`` out from the face."""
        x0, y0, x1, y1 = rect
        a, b = self.step_in, self.step_in + NEAR
        strip = {
            W: (x0 - b, y0, x0 - a, y1),
            E: (x1 + a, y0, x1 + b, y1),
            S: (x0, y0 - b, x1, y0 - a),
            N: (x0, y1 + a, x1, y1 + b),
        }[f]
        span = max((x1 - x0) if f in (N, S) else (y1 - y0), 1e-6)
        inside = self._over(strip) / (NEAR * span)
        return max(0.0, inside - 1.0 + min(need or span, span) / span)

    def _extent(self, rects, i: int, axis: int) -> tuple[float, float] | None:
        """How far room ``i`` and its wings reach across ``axis`` (0: west to
        east; 1: south to north), or None when it is not down."""
        if rects[i] is None:
            return None
        parts = [
            rects[p]
            for p in self.whole.get(i, (i,))
            if p < len(rects) and rects[p] is not None
        ]
        return min(r[axis] for r in parts), max(r[axis + 2] for r in parts)

    def _under_ridge(self, axis: int, share: float, size: float) -> float:
        """Where the west (or south, for ``axis`` 1) side of a room ``size``
        wide (or deep) goes, for it to be under a ridge (see ``Room.ridge``):
        ``share`` of the space beside it, between the walls the roofs come
        down to, on that side."""
        low, high = self.under[axis], self.under[axis + 2]
        return low + share * (high - low - size)

    def _roofed_side(self, rects, k: int) -> bool:
        """Whether side ``k`` of the floor (west, south, east, north, as a
        rectangle's sides go) is under a roof: a room on it (or its wing) has
        a roof down to that face and no outside wall there, so the side is
        not over a wall of the floor below."""
        if not any(self.roofed):
            return False
        there = [(i, r) for i, r in enumerate(rects[: self.n]) if r is not None]
        if not there:
            return False
        side = (min if k < 2 else max)(r[k] for _, r in there)
        face = SIDE_FACE[k]
        return any(
            abs(r[k] - side) <= TOL and face in self.roofed[self.main.get(i, i)]
            for i, r in there
        )

    def _settle(self, rects: tuple, cost: float, tries: int):
        """A layout made better while it can be (or the tries run out): each
        room moved on its own (``_nudge``), and then each room and the rooms
        it is linked to lifted and put down again, which moves rooms that are
        in each other's way. Returns the layout, its cost and the tries left."""
        while tries > 0:
            rects, cost = self._slide(rects, cost)
            rects, cost, tries = self._nudge(rects, cost, tries)
            better = False
            for i in self._place_order((None,) * self.n):
                group = {i, *(j for j, _ in self.against[i] if j < self.n)}
                group |= {w for w, room in self.main.items() if room in group}
                group |= {self.main[w] for w in group if w in self.main}
                lifted = tuple(None if k in group else r for k, r in enumerate(rects))
                layouts, tried = self._put_down(lifted, self._place_order(lifted), 3)
                tries -= tried
                for new in layouts:
                    new_cost = self.cost(_Spots(new))
                    if new_cost < cost - 1e-9:
                        rects, cost, better = new, new_cost, True
                        break
                if better or tries <= 0:
                    break
            if not better:
                break
        return rects, cost, tries

    def _slide(self, rects: tuple, cost: float) -> tuple[tuple, float]:
        """The layout made better, if it can be, by moving a room under a
        ridge (with its wings) so that it is under it, or the whole floor so
        that one of them is (or they are, on average). Rooms moved one at a
        time cannot do it all: a floor of linked rooms stays where its first
        room went down, and a room is tried on its own lines, not its wings'.
        The whole floor moves only when it may slide."""
        if self.under is None:
            return rects, cost
        moves: dict[int, list[tuple[float, list[int]]]] = {0: [], 1: []}
        for i, ridges in enumerate(self.ridges):
            for axis, share in ridges:
                span = self._extent(rects, i, axis)
                if span is not None:
                    where = self._under_ridge(axis, share, span[1] - span[0])
                    group = [p for p in self.whole.get(i, (i,)) if p < self.n]
                    moves[axis].append((where - span[0], group))
        every = list(range(self.n))
        for axis, found in moves.items():
            tries = list(found)
            if self.free and found:
                tries += [(move, every) for move, _ in found]
                tries.append((sum(move for move, _ in found) / len(found), every))
            for move, group in tries:
                dx, dy = (move, 0.0) if axis == 0 else (0.0, move)
                new = tuple(
                    (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
                    if k in group and r is not None
                    else r
                    for k, r in enumerate(rects)
                )
                new_cost = self.cost(_Spots(new))
                if new_cost < cost - 1e-9:
                    rects, cost = new, new_cost
        return rects, cost

    def _nudge(self, rects: tuple, cost: float, tries: int):
        """Move each room (with its wings) to its best place with the others
        where they are, while that makes the layout better (or the tries run
        out). Returns the layout, its cost and the tries left."""
        better = True
        while better and tries > 0:
            better = False
            for i in range(self.n):
                if i in self.main:
                    group = [i]
                else:
                    group = [p for p in self.whole.get(i, [i]) if p < self.n]
                rest = list(rects)
                for p in group:
                    rest[p] = None
                old = rects[i]
                for rect in self._spots(tuple(rest), i):
                    if rect == old:
                        continue
                    new = list(rest)
                    new[i] = rect
                    dx, dy = rect[0] - old[0], rect[1] - old[1]
                    for p in group[1:]:
                        r = rects[p]
                        new[p] = (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
                    if len(group) > 1 and any(
                        _into(new[p], other) > SLACK
                        for p in group[1:]
                        for k, other in enumerate([*new, *self.fixed])
                        if k not in group and other is not None
                    ):
                        continue
                    tries -= 1
                    new_cost = self.cost(_Spots(tuple(new)))
                    if new_cost < cost - 1e-9:
                        rects, cost, better = tuple(new), new_cost, True
                        break
                    if tries <= 0:
                        break
                if tries <= 0:
                    break
        return rects, cost, tries


def _along(lo: float, hi: float, size: float, lines, ends_only: bool = False):
    """Where something ``size`` long may start along a side from ``lo`` to
    ``hi`` and share at least a doorway of it: at either end, or with its
    start or end on one of the ``lines`` (only at the ends, for a wing)."""
    need = min(SHARE, 0.6 * min(size, hi - lo))
    starts = {lo, hi - size}
    if not ends_only:
        for line in lines:
            starts |= {line, line - size}
    return [s for s in starts if min(s + size, hi) - max(s, lo) >= need - 1e-9]


def _rounded(rects: tuple) -> tuple:
    """A layout's rectangles to the centimetre, to tell layouts apart."""
    return tuple(None if r is None else tuple(round(v, 2) for v in r) for r in rects)


def _replace(state: _State, **changes) -> _State:
    values = {
        "tree": state.tree,
        "x": state.x,
        "y": state.y,
        "width": state.width,
        "voids": state.voids,
        "anchors": state.anchors,
    }
    values.update(changes)
    return _State(**values)


def _mirror(tree, how: int):
    """The tree mirrored east to west (0) or north to south (1), or with east
    and north changed over (2)."""
    if isinstance(tree, int):
        return tree
    first, second = _mirror(tree[1], how), _mirror(tree[2], how)
    if how == 2:
        return (1 - tree[0], first, second)
    if tree[0] == how:
        return (tree[0], second, first)
    return (tree[0], first, second)


def _grafts(tree, leaf):
    """The tree with a leaf cut in beside each of its parts, each way."""
    for path in (*_leaves(tree), *_cuts(tree)):
        part = _at(tree, path)
        for cut in (0, 1):
            yield _put(tree, path, (cut, part, leaf))
            yield _put(tree, path, (cut, leaf, part))


def _graft(tree, leaf, rng: random.Random):
    """The tree with a leaf cut in beside one of its parts."""
    paths = [*_leaves(tree), *_cuts(tree)]
    path = rng.choice(paths)
    part = _at(tree, path)
    new = (
        (rng.randrange(2), part, leaf)
        if rng.random() < 0.5
        else (
            rng.randrange(2),
            leaf,
            part,
        )
    )
    return _put(tree, path, new)


def fit(floor: Floor, seed: int = SEED) -> dict[str, Rect]:
    """Fit one floor's rooms together: each room's rectangle, by its key."""
    return _Fit(floor).solve(floor, seed)


def cost_of(floor: Floor, placed: dict[str, Rect]) -> dict[str, float]:
    """What is still wrong with a layout: its cost by fault (0 for none).

    Only the faults that can be told from the rectangles are counted (links,
    walls, bare faces, rooms touching that are not linked, overlaps, rooms not
    over each other or their footprint).
    """
    solver = _Fit(floor)
    rects = [placed[r.key] for r in floor.rooms]
    solver.layout = lambda state: (  # type: ignore[method-assign]
        rects,
        [*rects],
        (
            min(r[0] for r in rects),
            min(r[1] for r in rects),
            max(r[2] for r in rects),
            max(r[3] for r in rects),
        ),
    )
    detail: dict[str, float] = {}
    solver.cost(None, detail)  # type: ignore[arg-type]
    left_out = ("shape", "voids", "envelope", "flush", "cover")
    return {k: v for k, v in detail.items() if k not in left_out}


# --- the outline ----------------------------------------------------------


def outline_cells(
    points: list[tuple[float, float]], area: float
) -> tuple[list[Rect], list[float], float]:
    """A building outline as rectangles, scaled to a floor area.

    The outline is measured round the outside of the walls, and the rooms
    inside them, so it is shrunk until it is as big as the rooms; but no
    smaller than ``FILL`` of its own area. Rooms smaller than that leave floor
    that no room was given (a hallway, the stairs): the outline keeps its
    size, and the rooms are fitted with a void as big as what is left. The
    outline's own south-west corner goes to 0, 0, where positions are
    measured from, and it is shrunk towards its middle, so each side comes in
    by about the outside wall's thickness.

    Args:
        points: The corners in the house's grid (east, north), in metres.
        area: The floor area the outline is to have.

    Returns:
        The rectangles that make up the outline, the area of each notch
        between it and the rectangle round it (and then of the floor no room
        was given, if any), and that rectangle's width.
    """
    if len(points) < 3:
        return [], [], 0.0

    def lines(values: list[float]) -> list[float]:
        groups: list[list[float]] = []
        for value in sorted(values):
            if groups and value - groups[-1][0] <= JOG:  # these share a line
                groups[-1].append(value)
            else:
                groups.append([value])
        # the outline's own sides stay where they are; a line inside it goes
        # to the middle of its corners
        out = [(min(group) + max(group)) / 2 for group in groups]
        out[0], out[-1] = groups[0][0], groups[-1][-1]
        return out

    xs, ys = lines([p[0] for p in points]), lines([p[1] for p in points])
    if len(xs) < 2 or len(ys) < 2:
        return [], [], 0.0

    def inside(x: float, y: float) -> bool:
        hit = False
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                hit = not hit
        return hit

    filled = {
        (i, j)
        for i in range(len(xs) - 1)
        for j in range(len(ys) - 1)
        if inside((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2)
    }

    def size(cell: tuple[int, int]) -> float:
        return (xs[cell[0] + 1] - xs[cell[0]]) * (ys[cell[1] + 1] - ys[cell[1]])

    own = sum(size(cell) for cell in filled)
    if own <= 0:
        return [], [], 0.0
    shrink = math.sqrt(max(area, FILL * own) / own)
    mid_x, mid_y = (xs[-1] - xs[0]) / 2, (ys[-1] - ys[0]) / 2

    def x_of(i: int) -> float:
        return mid_x + (xs[i] - xs[0] - mid_x) * shrink

    def y_of(j: int) -> float:
        return mid_y + (ys[j] - ys[0] - mid_y) * shrink

    rects = [(x_of(i), y_of(j), x_of(i + 1), y_of(j + 1)) for i, j in sorted(filled)]
    # the notches: each group of empty cells that touch
    empty = {(i, j) for i in range(len(xs) - 1) for j in range(len(ys) - 1)} - filled
    notches: list[float] = []
    while empty:
        todo = [empty.pop()]
        notch = 0.0
        while todo:
            i, j = todo.pop()
            notch += size((i, j)) * shrink * shrink
            for near in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if near in empty:
                    empty.remove(near)
                    todo.append(near)
        notches.append(notch)
    notches = [v for v in notches if v > 0.02 * area]
    spare = own * shrink * shrink - area
    if spare > 0.02 * area:
        notches.append(spare)
    return rects, notches, (xs[-1] - xs[0]) * shrink


# --- the whole house ------------------------------------------------------


def _aim(floor: Floor) -> None:
    """Start a floor as wide as the rooms it is above (or below) are together,
    with a void for what its own rooms leave of them, if that is no more than
    could be halls: floors of a house are most often the same size."""
    if not floor.stack or floor.fixed or floor.width:
        return
    wide = max(r[2] for _, r in floor.stack) - min(r[0] for _, r in floor.stack)
    deep = max(r[3] for _, r in floor.stack) - min(r[1] for _, r in floor.stack)
    area = sum(room.area for room in floor.rooms)
    spare = wide * deep - area
    if spare > HALLS * area or spare < -0.1 * area:
        return
    floor.width = wide
    if spare > 0.02 * area:
        floor.voids = [spare]


def _grown(rect: Rect, half: float, near: int | None = None) -> Rect:
    """A rectangle ``half`` bigger all round (smaller, for ``half`` below 0).
    A wing has no wall against its room: its side there (``near``) moves the
    other way, so the two stay flush."""
    out = [rect[0] - half, rect[1] - half, rect[2] + half, rect[3] + half]
    if near is not None:
        k = {W: 0, S: 1, E: 2, N: 3}[near]
        out[k] += 2 * half if k < 2 else -2 * half
    return (out[0], out[1], out[2], out[3])


def _grown_room(room: Room, wall: float, along: str | None = None) -> Room:
    """A room a wall bigger (half a wall each side), to be fitted against its
    neighbours as if it were measured to the middles of its walls. A wing
    (against its room's ``along`` face) grows only along that face."""
    walls = tuple((f, length + wall if length > 0 else 0.0) for f, length in room.walls)
    if room.size:
        wide, deep = room.size
        if along is None:
            size = (wide + wall, deep + wall)
        elif along in ("E", "W"):
            size = (wide, deep + wall)
        else:
            size = (wide + wall, deep)
        return replace(room, area=size[0] * size[1], size=size, walls=walls)
    side = math.sqrt(room.area)
    area = (side + wall) ** 2 if along is None else (side + wall) * side
    return replace(room, area=area, walls=walls)


def arrange(
    floors: list[Floor],
    above: list[tuple[str, str]],
    outline: list[tuple[float, float]] | None = None,
    holes: dict[str, list[Rect]] | None = None,
    grid: float | None = None,
    mirror: list[tuple[str, ...]] | None = None,
    wall: float = 0.0,
) -> dict[str, Rect]:
    """Fit every floor, and the floors over each other.

    The biggest floor is fitted first, to the building outline when there is
    one (else a floor with rooms already placed is first). Each other floor,
    nearest first, is then fitted where its rooms sit over (or under) the
    rooms they are above, and over the first floor's footprint, its sides on
    the footprint's where it is big enough. A room already placed is where
    the building outline's south-west corner is 0, 0.

    Args:
        floors: The floors, lowest first. Each floor's ``stack``, ``support``
            and ``free`` are worked out here.
        above: ``(lower, upper)`` for each room above another.
        outline: The building outline's corners in the house's grid.
        holes: Filled with each room's floor's holes (space no room was
            given, with rooms all round it), by the room's key.
        grid: The step houses are built to, in metres (an inch, say). The
            walls of the rooms that are shaped to fit are put on whole steps,
            so each is a whole number of steps wide and deep: a house is
            built 12 feet 6 wide, not 12 feet 6.3. A room with a width and
            depth keeps them, with its south-west corner on a step.
        mirror: Groups of keys that take the same rectangle, such as a flight
            of stairs and its opening on the floor above. Whichever of a group
            is placed first, the others are fixed where it is.
        wall: How thick a wall between two rooms is, in metres. Rooms are
            measured inside, so two rooms side by side are a wall apart: each
            is fitted half a wall bigger all round (a wing, which has no wall
            against its room, only along it), and comes back its own size.

    Returns:
        Every room's rectangle by its key, the already placed rooms included.
    """
    half = wall / 2 if wall > 0 else 0.0
    sizes = {r.key: r.size for floor in floors for r in floor.rooms if r.size}
    near: dict[str, int] = {}  # each wing's side against its room
    if half:
        for floor in floors:
            # a wing's face against its room (or its room's other wing)
            faces = {
                b: f
                for a, b, f in floor.links
                if f
                and a != b
                and b in floor.wings
                and floor.wings[b] in (a, floor.wings.get(a))
            }
            near.update({k: _OPPOSITE[FACE_INDEX[f]] for k, f in faces.items()})
            floor.rooms = [_grown_room(r, wall, faces.get(r.key)) for r in floor.rooms]
            floor.fixed = {
                k: _grown(r, half, near.get(k)) for k, r in floor.fixed.items()
            }
    group_of: dict[str, tuple[str, ...]] = {}
    for group in mirror or ():
        for key in group:
            group_of[key] = group
    placed: dict[str, Rect] = {}
    for floor in floors:
        placed.update(floor.fixed)
    pinned = bool(placed)
    copies: dict[str, str] = {}  # a mirrored key: the key it takes its place from

    def take_mirrors(floor: Floor) -> None:
        for room in list(floor.rooms):
            done = [k for k in group_of.get(room.key, ()) if k in placed]
            if done:
                floor.rooms.remove(room)
                floor.fixed[room.key] = placed[done[0]]
                placed[room.key] = placed[done[0]]
                copies[room.key] = done[0]

    for floor in floors:
        take_mirrors(floor)
    footprint: list[Rect] = []  # the first floor, for the others to line up with
    under: Rect | None = None  # round its rooms with no roof: see ``Floor.under``
    live = [i for i, floor in enumerate(floors) if floor.rooms]
    if not live:  # every room is placed already
        return {k: _grown(r, -half, near.get(k)) for k, r in placed.items()}

    def weight(i: int) -> tuple:
        # with an outline, the biggest floor is fitted to it: rooms placed on
        # another floor are where the outline is too
        return (
            bool(floors[i].fixed) and not outline,
            sum(r.area for r in floors[i].rooms),
        )

    first = max(live, key=weight)
    for i in sorted(live, key=lambda i: (i != first, abs(i - first), i)):
        floor = floors[i]
        take_mirrors(floor)
        if not floor.rooms:  # every room on it takes its place from another floor
            if i == first:
                footprint = [*floor.fixed.values()]
            continue
        keys = {r.key for r in floor.rooms}
        floor.stack = [
            (key, placed[other])
            for low, high in above
            for key, other in ((low, high), (high, low))
            if key in keys and other in placed
        ]
        if i == first:
            floor.free = pinned
            if outline:
                area = sum(r.area for r in floor.rooms)
                area += sum((r[2] - r[0]) * (r[3] - r[1]) for r in floor.fixed.values())
                cells, notches, width = outline_cells(outline, area)
                if cells:
                    floor.support = cells
                    if not floor.fixed:  # else its voids go round what is placed
                        floor.width, floor.voids = width, notches
        else:
            floor.free = True
            floor.support = footprint
            floor.step_in = STEP_IN
            floor.under = under
            _aim(floor)
        solver = _Fit(floor)
        found = solver.solve(floor)
        if holes is not None and solver.holes:
            for key in (*found, *floor.fixed):
                holes[key] = solver.holes
        placed.update(found)
        if i == first:
            footprint = [*found.values(), *floor.fixed.values(), *solver.holes]
            # the walls the roofs over it stand on: round the rooms that have
            # no roof of their own (a wing's is its room's)
            roofed = {r.key for r in floor.rooms if r.eaves}
            roofed |= {w for w, room in floor.wings.items() if room in roofed}
            bare = [r for k, r in found.items() if k not in roofed]
            bare = [*bare, *floor.fixed.values(), *solver.holes] or footprint
            under = (
                min(r[0] for r in bare),
                min(r[1] for r in bare),
                max(r[2] for r in bare),
                max(r[3] for r in bare),
            )
    if half:  # each room back to its own size
        for key, rect in placed.items():
            placed[key] = _grown(rect, -half, near.get(key))
        if holes is not None:
            for key, rects in holes.items():
                holes[key] = [_grown(r, -half) for r in rects]
    if grid and grid > 0:
        loose = {r.key for floor in floors for r in floor.rooms}
        for key in loose:
            placed[key] = _on_grid(placed[key], grid, sizes.get(key))
        if holes is not None:
            for key, rects in holes.items():
                holes[key] = [_on_grid(rect, grid) for rect in rects]
    for key, partner in copies.items():  # a mirror is the same rectangle as its partner
        placed[key] = placed[partner]
    return placed


def _on_grid(rect: Rect, grid: float, size: tuple[float, float] | None = None) -> Rect:
    """A rectangle with its sides on whole steps of the grid (or, for a room
    that keeps its size, its south-west corner)."""

    def snap(value: float) -> float:
        return round(value / grid) * grid

    if size:
        x, y = snap(rect[0]), snap(rect[1])
        return (x, y, x + size[0], y + size[1])
    return (snap(rect[0]), snap(rect[1]), snap(rect[2]), snap(rect[3]))
