# Copyright (c) 2026 MinchinWeb
"""Measure how far the house is turned off the compass grid, and draw it.

The building outline comes from OpenStreetMap (Nominatim, else Overpass). The
rotation is the length-weighted bearing of its walls modulo 90 degrees,
positive when the house is turned clockwise from north, which is the same as
its south-facing wall looking a little west of south. The house form measures
it at the Home Assistant home position and draws it (see ``map_view.py``).
Standard library only.
"""

from __future__ import annotations

import itertools
import json
import math
import urllib.parse
import urllib.request

OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
METRES_PER_DEGREE = 111_320.0

Point = tuple[float, float]  # (latitude, longitude)


def _metres(a: Point, b: Point) -> tuple[float, float]:
    """East and north distance in metres from ``a`` to ``b``."""
    return (
        (b[1] - a[1]) * METRES_PER_DEGREE * math.cos(math.radians(a[0])),
        (b[0] - a[0]) * METRES_PER_DEGREE,
    )


def wall_rotation(outline: list[Point]) -> tuple[float, float]:
    """Rotation off the compass grid, and how square the outline is.

    Walls repeat every 90 degrees, so the angles are multiplied by four before
    averaging (weighted by wall length).

    Args:
        outline: The corners, in order (a closed way repeats the first).

    Returns:
        The rotation in degrees, in (-45, 45], and the squareness from 0 to 1
        (1 when every wall lies on one grid).

    Raises:
        ValueError: The outline has no walls.
    """
    sin_sum = cos_sum = total = 0.0
    for a, b in itertools.pairwise(outline):
        east, north = _metres(a, b)
        length = math.hypot(east, north)
        bearing = math.degrees(math.atan2(east, north)) % 180.0
        sin_sum += length * math.sin(math.radians(4 * bearing))
        cos_sum += length * math.cos(math.radians(4 * bearing))
        total += length
    if total == 0:
        raise ValueError("the outline has no walls")
    turn = math.degrees(math.atan2(sin_sum, cos_sum)) / 4.0
    if turn > 45:
        turn -= 90
    return turn, math.hypot(sin_sum, cos_sum) / total


def outline_walls(outline: list[Point]) -> list[tuple[float, float]]:
    """The outline's walls as the way each faces and its length.

    Args:
        outline: The corners, in order, either way round.

    Returns:
        For each wall, its outward compass bearing in degrees and its length in
        metres; no positions, so the result does not give away where it is.
    """
    if len(outline) < 3:
        return []
    ring = list(outline)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    sides = [_metres(a, b) for a, b in itertools.pairwise(ring)]
    # shoelace on the corners relative to the first: positive when anticlockwise
    x = y = twice_area = 0.0
    for east, north in sides:
        twice_area += x * (y + north) - (x + east) * y
        x, y = x + east, y + north
    # outward is to the right of the way round when it runs anticlockwise
    turn = 90.0 if twice_area > 0 else -90.0
    return [
        (
            round((math.degrees(math.atan2(east, north)) + turn) % 360.0, 1),
            round(math.hypot(east, north), 2),
        )
        for east, north in sides
        if east or north
    ]


def _inside(point: Point, outline: list[Point]) -> bool:
    lat, lon = point
    inside = False
    for (lat1, lon1), (lat2, lon2) in itertools.pairwise(outline):
        if (lat1 > lat) != (lat2 > lat) and lon < lon1 + (lat - lat1) * (
            lon2 - lon1
        ) / (lat2 - lat1):
            inside = not inside
    return inside


def choose_outline(outlines: list[list[Point]], home: Point) -> list[Point] | None:
    """The outline around ``home``, else the one with the nearest corner."""
    for outline in outlines:
        if _inside(home, outline):
            return outline
    if not outlines:
        return None
    return min(
        outlines,
        key=lambda o: min(math.hypot(*_metres(home, p)) for p in o),
    )


def ring_from_nominatim(body: dict) -> list[Point] | None:
    """The building polygon in a Nominatim reverse-geocoding answer, if it is one."""
    geometry = body.get("geojson") or {}
    if body.get("category") != "building" or geometry.get("type") != "Polygon":
        return None
    return [(lat, lon) for lon, lat in geometry["coordinates"][0]]


def _nominatim(lat: float, lon: float) -> list[Point] | None:
    query = urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "zoom": 18, "polygon_geojson": 1, "format": "jsonv2"}
    )
    request = urllib.request.Request(
        f"{NOMINATIM}?{query}", headers={"User-Agent": "house-structure/0.1"}
    )
    with urllib.request.urlopen(request, timeout=15) as resp:
        return ring_from_nominatim(json.load(resp))


def fetch_outlines(lat: float, lon: float, radius: int = 40) -> list[list[Point]]:
    """Building outlines at a position (blocking).

    Nominatim names the building under the point in one quick request; if that
    fails or finds none, the Overpass servers list every building within
    ``radius`` metres (they are often busy).
    """
    try:
        ring = _nominatim(lat, lon)
    except OSError, ValueError, KeyError:
        ring = None
    if ring:
        return [ring]
    query = f'[out:json];way(around:{radius},{lat},{lon})["building"];out geom;'
    body = urllib.parse.urlencode({"data": query}).encode()
    error: OSError | None = None
    for url in OVERPASS:  # the public servers are often busy; try each
        request = urllib.request.Request(
            url, body, headers={"User-Agent": "house-structure/0.1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                ways = json.load(resp)["elements"]
            break
        except OSError as err:
            error = err
    else:
        raise error or OSError("no Overpass server answered")
    return [[(p["lat"], p["lon"]) for p in way["geometry"]] for way in ways]


def outline_svg(outline: list[Point], rotation: float, size: int = 280) -> str:
    """A drawing of the building with true north and the house's own axes.

    The faint dashed cross is true north-south and east-west. The orange cross
    is that cross turned by ``rotation``: if it lines up with the walls, the
    rotation is right. The dot marks where the south wall faces. The caption
    sits in a strip below the drawing, so the dot never covers it.
    """
    home = outline[0]
    xs, ys = [], []
    for p in outline:
        east, north = _metres(home, p)
        xs.append(east)
        ys.append(north)
    cx_m, cy_m = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    scale = size * 0.5 / span
    mid = size / 2

    def at(east: float, north: float) -> str:
        return f"{mid + (east - cx_m) * scale:.1f},{mid - (north - cy_m) * scale:.1f}"

    polygon = " ".join(at(x, y) for x, y in zip(xs, ys, strict=True))
    turn = math.radians(rotation)
    reach = size * 0.44
    height = size + 24  # the caption's strip
    # the house's own north-south and east-west axes, turned by the rotation
    axes = "".join(
        f'<line x1="{mid - reach * dx:.1f}" y1="{mid + reach * dy:.1f}" '
        f'x2="{mid + reach * dx:.1f}" y2="{mid - reach * dy:.1f}" '
        f'stroke="#e0562b" stroke-width="2.5"/>'
        for dx, dy in (
            (math.sin(turn), math.cos(turn)),
            (math.cos(turn), -math.sin(turn)),
        )
    )
    azimuth = math.radians(180.0 + rotation)
    tip_x = mid + reach * math.sin(azimuth)
    tip_y = mid - reach * math.cos(azimuth)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{height}" '
        f'viewBox="0 0 {size} {height}" font-family="sans-serif" font-size="13">'
        f'<line x1="{mid}" y1="6" x2="{mid}" y2="{size - 6}" stroke="#888" '
        f'stroke-width="1" stroke-dasharray="4 4"/>'
        f'<line x1="6" y1="{mid}" x2="{size - 6}" y2="{mid}" stroke="#888" '
        f'stroke-width="1" stroke-dasharray="4 4"/>'
        f'<polygon points="{polygon}" fill="rgba(110,150,220,0.35)" '
        f'stroke="#4a78c8" stroke-width="2"/>'
        f"{axes}"
        f'<circle cx="{tip_x:.1f}" cy="{tip_y:.1f}" r="5" fill="#e0562b"/>'
        f'<text x="{mid + 6}" y="18" fill="#888">N</text>'
        f'<text x="6" y="{height - 7}" fill="#e0562b">'
        f"south wall faces {180.0 + rotation:.0f}° (rotation {rotation:+.1f}°)"
        f"</text></svg>"
    )
