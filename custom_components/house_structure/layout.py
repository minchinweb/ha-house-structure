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
same house always gives the same layout) to get out of a dead end. A layout
costs more for:

* linked rooms that do not share a wall (or share the wrong face);
* an outside wall with another room against it, or shorter than its length;
* a face with no outside wall that is left on the outside;
* rooms touching that are not linked (when both have links to other rooms);
* long thin rooms, and a long thin house;
* voids, by their size;
* a room not over the room it is above, or outside the footprint under it
  (the building outline, when there is one).

Floors are fitted one at a time, starting with the biggest; the others are
then free to slide over it to where their rooms sit above the ones below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random

Rect = tuple[float, float, float, float]  # west, south, east, north (metres)

N, E, S, W = 0, 1, 2, 3
FACE_INDEX = {"N": N, "E": E, "S": S, "W": W}
_OPPOSITE = (S, W, N, E)

TOL = 0.05  # m: edges this close are the same edge
NEAR = 0.6  # m: a room this close to a face covers it
SHARE = 0.8  # m: linked rooms share at least this much wall (a doorway)
MAX_VOIDS = 3
BEAM = 6  # layouts kept while the rooms are added one at a time
TRIES = 2200  # layouts tried for each room (and void) on a floor
TRIES_MOST = 24000
TIDY = 800  # tries kept back for the last improving
TRIES_LEAST = {1: 400, 2: 2000, 3: 6000}  # for a floor of so few; 12000 for more
HEAT, COOL = 2.0, 0.01  # the search's first heat, and how far it falls
SOFT = 0.1  # how much a wrong size costs when the search starts (see ``stiff``)
SEED = 20261113

# What each fault costs. A link that is not met costs about W_LINK; lengths
# are counted against the side of a square as big as the floor, and areas
# against the floor's area, so a big house costs the same as a small one.
W_LINK = 10.0
W_FACE = 4.0  # linked, but not on the face the internal wall names
W_WALL = 6.0  # an outside wall that is covered, or too short
W_FULL = 1.5  # an outside wall with no length, partly covered
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
    """

    key: str
    area: float
    size: tuple[float, float] | None = None
    walls: tuple[tuple[str, float], ...] = ()
    eaves: frozenset[str] = frozenset()
    long: bool = False


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
    """

    rooms: list[Room]
    fixed: dict[str, Rect] = field(default_factory=dict)
    links: list[tuple[str, str, str | None]] = field(default_factory=list)
    stack: list[tuple[str, Rect]] = field(default_factory=list)
    support: list[Rect] = field(default_factory=list)
    free: bool = False
    width: float | None = None
    voids: list[float] = field(default_factory=list)


@dataclass
class _State:
    """One layout being tried."""

    tree: object  # a leaf's number, or (cut, first, second)
    x: float
    y: float
    width: float
    voids: tuple[float, ...]
    anchors: tuple[tuple[int, int], ...]  # each room's corner of its piece


def _overlap(a: Rect, b: Rect) -> float:
    """The area two rectangles share."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    d = min(a[3], b[3]) - max(a[1], b[1])
    return w * d if w > 0 and d > 0 else 0.0


def _apart(a: Rect, b: Rect) -> float:
    """How far apart two rectangles are, east-west plus north-south."""
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return dx + dy


def _on_edge(cell: Rect, envelope: Rect) -> bool:
    """Whether a piece is on the edge of the floor's rectangle."""
    return any(abs(cell[k] - envelope[k]) < TOL for k in range(4))


def linked_across(a: Rect, b: Rect, holes: list[Rect]) -> bool:
    """Whether two rooms both open on to one of the holes."""
    for hole in holes:
        _, pairs = _contacts([hole, a, b])
        if (0, 1) in pairs and (0, 2) in pairs:
            return True
    return False


def _contacts(rects: list):
    """Which rectangles are side by side: for each one, the stretches of its
    faces that others cover (from up to ``NEAR`` away, so a sliver of a gap
    does not make an outside wall), and for each pair that touches, the face
    of the first and the length they share."""
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
            if hi - lo > 1e-6:
                gap = bx0 - ax1
                side = E
                if gap < -TOL:
                    gap, side = ax0 - bx1, W
            else:
                lo, hi = max(ax0, bx0), min(ax1, bx1)
                if hi - lo <= 1e-6:
                    continue
                gap = by0 - ay1
                side = N
                if gap < -TOL:
                    gap, side = ay0 - by1, S
            if gap < -TOL or gap > NEAR:
                continue
            faces[i][side].append((lo, hi))
            faces[j][_OPPOSITE[side]].append((lo, hi))
            if gap < TOL:
                pairs[(i, j)] = (side, hi - lo)
    return faces, pairs


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
        self.has_links = {i for pair in self.linked for i in pair}
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
        index_of = {r.key: i for i, r in enumerate(floor.rooms)}
        self.stack = [(index_of[k], rect) for k, rect in floor.stack if k in index_of]
        self.support = floor.support
        self.free = floor.free
        others = [*self.fixed, *(r for _, r in self.stack), *self.support]
        self.xs = sorted({r[0] for r in others} | {r[2] for r in others})
        self.ys = sorted({r[1] for r in others} | {r[3] for r in others})
        self.max_voids = min(MAX_VOIDS + len(self.fixed), 5)
        self.holes: list[Rect] = []  # the holes in the layout ``solve`` found
        self.middle = None  # of the footprint, for a floor that may slide
        if self.support:
            self.middle = (
                (min(r[0] for r in self.support) + max(r[2] for r in self.support)) / 2,
                (min(r[1] for r in self.support) + max(r[3] for r in self.support)) / 2,
            )
        # How much a room of the wrong size costs, against its full cost. The
        # search starts with it low, so that a layout can pass through wrong
        # sizes on its way to a better one, and ends with it whole.
        self.stiff = 1.0

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

    def layout(self, state: _State):
        """Each room's rectangle, each leaf's piece, and the whole rectangle."""
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
        if dx or dy:
            rects = [r and (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy) for r in rects]
            cells = [c and (c[0] + dx, c[1] + dy, c[2] + dx, c[3] + dy) for c in cells]
        return rects, cells, (dx, dy, dx + width, dy + depth)

    def cost(self, state: _State, detail: dict | None = None) -> float:
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
        faces, pairs = _contacts(every)
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
            if got is not None and got[1] >= need:
                if want is not None and got[0] != want:
                    parts["links"] += W_FACE
            elif any(
                pairs.get((i, h), (0, 0.0))[1] >= need
                and pairs.get((j, h), (0, 0.0))[1] >= need
                for h in range(first_hole, len(every))
            ):
                parts["links"] += W_ACROSS
            elif got is not None:
                parts["links"] += W_LINK * (1.0 - 0.5 * got[1] / need)
            else:
                parts["links"] += W_LINK * (1.0 + _apart(a, b) / scale)
        for i in range(n):
            if rects[i] is None:
                continue
            x0, y0, x1, y1 = rects[i]
            walls, eaves = self.walls[i], self.eaves[i]
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
            if (
                i < n
                and (i, j) not in self.linked
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
            for rect in placed:
                area = (rect[2] - rect[0]) * (rect[3] - rect[1])
                held = sum(_overlap(rect, other) for other in self.support)
                parts["support"] += W_SUPPORT * max(0.0, area - held) / total
        if detail is not None:
            detail.update(parts)
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
        if len(state.voids) < self.max_voids:
            voids = (*state.voids, 0.08 * self.total)
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
        in the layouts so far, and the best few are kept for the next."""
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
        now, now_cost = best, best_cost
        seen, seen_cost = best, best_cost  # the best while annealing
        for step in range(steps):
            done = step / steps
            heat = HEAT * (COOL**done)
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
        self.stiff = 1.0
        for state in (seen, now):
            state, cost, _ = self._improve(state, self.cost(state), keep // 2)
            if cost < best_cost:
                best, best_cost = state, cost
        rects, cells, envelope = self.layout(self._tidy(best))
        self.holes = [c for c in cells[self.n :] if not _on_edge(c, envelope)]
        return {room.key: rect for room, rect in zip(self.rooms, rects, strict=True)}

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
    return {k: v for k, v in detail.items() if k not in ("shape", "voids", "envelope")}


# --- the outline ----------------------------------------------------------


def outline_cells(
    points: list[tuple[float, float]], area: float
) -> tuple[list[Rect], list[float], float]:
    """A building outline as rectangles, scaled to a floor area.

    The outline is measured round the outside of the walls, and the rooms
    inside them, so it is shrunk until it is as big as the rooms. Its
    south-west corner goes to 0, 0.

    Args:
        points: The corners in the house's grid (east, north), in metres.
        area: The floor area the outline is to have.

    Returns:
        The rectangles that make up the outline, the area of each notch
        between it and the rectangle round it, and that rectangle's width.
    """
    if len(points) < 3:
        return [], [], 0.0

    def lines(values: list[float]) -> list[float]:
        out: list[float] = []
        for value in sorted(values):
            if not out or value - out[-1] > 0.3:  # corners this close share a line
                out.append(value)
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
    shrink = math.sqrt(area / own)
    rects = [
        (
            (xs[i] - xs[0]) * shrink,
            (ys[j] - ys[0]) * shrink,
            (xs[i + 1] - xs[0]) * shrink,
            (ys[j + 1] - ys[0]) * shrink,
        )
        for i, j in sorted(filled)
    ]
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
    return rects, notches, (xs[-1] - xs[0]) * shrink


# --- the whole house ------------------------------------------------------


def arrange(
    floors: list[Floor],
    above: list[tuple[str, str]],
    outline: list[tuple[float, float]] | None = None,
    holes: dict[str, list[Rect]] | None = None,
) -> dict[str, Rect]:
    """Fit every floor, and the floors over each other.

    The biggest floor (or one with rooms already placed) is fitted first, to
    the building outline when there is one. Each other floor, nearest first,
    is then fitted where its rooms sit over (or under) the rooms they are
    above, and over the first floor's footprint.

    Args:
        floors: The floors, lowest first. Each floor's ``stack``, ``support``
            and ``free`` are worked out here.
        above: ``(lower, upper)`` for each room above another.
        outline: The building outline's corners in the house's grid.
        holes: Filled with each room's floor's holes (space no room was
            given, with rooms all round it), by the room's key.

    Returns:
        Every room's rectangle by its key, the already placed rooms included.
    """
    placed: dict[str, Rect] = {}
    for floor in floors:
        placed.update(floor.fixed)
    pinned = bool(placed)
    live = [i for i, floor in enumerate(floors) if floor.rooms]
    if not live:
        return placed

    def weight(i: int) -> tuple:
        return (bool(floors[i].fixed), sum(r.area for r in floors[i].rooms))

    first = max(live, key=weight)
    support: list[Rect] = []
    for i in sorted(live, key=lambda i: (i != first, abs(i - first), i)):
        floor = floors[i]
        keys = {r.key for r in floor.rooms}
        floor.stack = [
            (key, placed[other])
            for low, high in above
            for key, other in ((low, high), (high, low))
            if key in keys and other in placed
        ]
        if i == first:
            floor.free = pinned
            if outline and not pinned:
                area = sum(r.area for r in floor.rooms)
                cells, notches, width = outline_cells(outline, area)
                if cells:
                    support, floor.width, floor.voids = cells, width, notches
            floor.support = support
        else:
            floor.free = True
            floor.support = support
        solver = _Fit(floor)
        found = solver.solve(floor)
        if holes is not None and solver.holes:
            for key in (*found, *floor.fixed):
                holes[key] = solver.holes
        placed.update(found)
        if i == first and not support:
            support = [*found.values(), *floor.fixed.values()]
    return placed
