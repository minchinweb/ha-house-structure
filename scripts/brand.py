# Copyright (c) 2026 MinchinWeb
# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools", "uharfbuzz"]
# ///
"""Draw the brand icons, logos and sidebar icons of the three house integrations.

House Structure, Home Thermal Lab and Manual J share one look: an isometric
mark at the 30 degree angle the house drawings use (``drawing.py``), in the
drawings' own colours, with no backing disc. This script is the one source of
that look. For each integration it writes:

* ``brand/icon.svg``, ``dark_icon.svg``, ``logo.svg`` and ``dark_logo.svg`` at
  the repository root (the sources), and
* ``custom_components/<domain>/brand/`` with each of those as a PNG at 1x and
  ``@2x``, which Home Assistant 2026.3 and newer shows on the integration's
  pages.

For House Structure it also writes the sidebar icon set: one-colour versions of
the three marks in ``brand/icons/``, and
``custom_components/house_structure/frontend/icons.js``, which registers them
as ``minchinweb:house``, ``minchinweb:thermal-lab``,
``minchinweb:manual-j`` and ``minchinweb:sun-sweep``, plus
``minchinweb:room-hallway``, ``minchinweb:double-sinks``,
``minchinweb:room-bedroom`` and the bedrooms labelled with a direction, a
number or a letter (``minchinweb:room-bedroom-ne`` and so on). And
``brand/drafting.svg`` (and ``.png``): the house with its hidden edges dashed,
for large uses such as the README. The
hidden edges are left out of the brand PNGs, which Home Assistant shows at
about 40 px.

The logo's name is drawn in Figtree SemiBold, outlined to paths so it looks
the same everywhere. The font is in ``brand/fonts/`` with its licence (SIL Open
Font License 1.1).

Needs ``inkscape`` (1.2 or newer) and ``optipng`` on the path. The other
repositories are looked for next to this one.

Examples::

    uv run scripts/brand.py
    uv run scripts/brand.py --scheme blueprint --only house_structure
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
import uharfbuzz as hb

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "brand" / "fonts" / "Figtree-Variable.ttf"
CANVAS = 512  # the marks are drawn on a 512 square
ICON_SIZE = 256  # icon.png; icon@2x.png is twice this
LOGO_HEIGHT = 128  # logo.png; logo@2x.png is twice this
FONT_WEIGHT = 600
ICON_PREFIX = "minchinweb"

# The house drawings' colours (drawing.py), with brown ink. The forecast curves
# keep heat, solar and cold colours in every scheme, because the colours say
# which is which.
SCHEMES: dict[str, dict[str, dict[str, dict[str, str]]]] = {
    "drawing": {
        "house": {
            "light": {
                "f0": "#9c7b6b", "f1": "#e2d3ae", "f2": "#c9b78c",
                "ink": "#4e342e", "door": "#a8744a", "win": "#9fd3f0",
            },
            "dark": {
                "f0": "#b39486", "f1": "#efe3c4", "f2": "#d8c79f",
                "ink": "#3a2722", "door": "#a8744a", "win": "#9fd3f0",
            },
        },
        "thermal-lab": {
            "light": {
                "past": "#4e342e", "heat": "#e0562b", "solar": "#d99a00",
                "cold": "#1f77b4",
            },
            "dark": {
                "past": "#f3efe6", "heat": "#ff7a50", "solar": "#ffc94a",
                "cold": "#5cc8ff",
            },
        },
        "manual-j": {
            "light": {
                "cover": "#8a5a3b", "board": "#a8744a", "inner": "#5c3b1e",
                "spine": "#6f4529", "band": "#d9b77a", "pages": "#f3efe6",
                "pageline": "#cfc6b2", "ink": "#3e2716", "j": "#f0d58a",
            },
            "dark": {
                "cover": "#9c6a48", "board": "#b8845a", "inner": "#5c3b1e",
                "spine": "#7d5233", "band": "#e6c88e", "pages": "#f3efe6",
                "pageline": "#cfc6b2", "ink": "#2e1d10", "j": "#f5df9e",
            },
        },
        "text": {"light": {"fill": "#4e342e"}, "dark": {"fill": "#f3efe6"}},
    },
    "blueprint": {
        "house": {
            "light": {
                "f0": "#dceaf7", "f1": "#a9cbea", "f2": "#6e9fd0",
                "ink": "#0f3d6e", "door": "#0f3d6e", "win": "#f3f9fd",
            },
            "dark": {
                "f0": "#dceaf7", "f1": "#9cc2e6", "f2": "#5e8fc4",
                "ink": "#0a2a4d", "door": "#0a2a4d", "win": "#f3f9fd",
            },
        },
        "thermal-lab": {
            "light": {
                "past": "#0f3d6e", "heat": "#e0562b", "solar": "#d99a00",
                "cold": "#4fb3e8",
            },
            "dark": {
                "past": "#dceaf7", "heat": "#ff7a50", "solar": "#ffc94a",
                "cold": "#5cc8ff",
            },
        },
        "manual-j": {
            "light": {
                "cover": "#1f5fa0", "board": "#3d7fc0", "inner": "#0f3d6e",
                "spine": "#174e86", "band": "#a9cbea", "pages": "#f3f7fb",
                "pageline": "#c5d4e3", "ink": "#0b2e55", "j": "#ffffff",
            },
            "dark": {
                "cover": "#2b6fb3", "board": "#4a8ccc", "inner": "#0f3d6e",
                "spine": "#1f5fa0", "band": "#b9d5ef", "pages": "#f3f7fb",
                "pageline": "#c5d4e3", "ink": "#0a2a4d", "j": "#ffffff",
            },
        },
        "text": {"light": {"fill": "#0f3d6e"}, "dark": {"fill": "#dceaf7"}},
    },
}  # fmt: skip


@dataclass(frozen=True)
class Integration:
    """One integration that gets a mark."""

    domain: str
    name: str
    repo: str  # the repository's folder name
    icon: str  # the mark, and its name in the sidebar icon set


INTEGRATIONS = (
    Integration("house_structure", "House Structure", "ha-house-structure", "house"),
    Integration(
        "home_thermal_lab", "Home Thermal Lab", "ha-home-thermal-lab", "thermal-lab"
    ),
    Integration("manual_j", "Manual J", "ha-manual-j", "manual-j"),
)

# --- the marks, on the 512 canvas -------------------------------------------
# The house: x runs to the right and up, y to the left and up, z up; a point
# (x, y, z) is drawn at ((x - y) cos 30, -(x + y) sin 30 - z), as drawing.py
# does. Footprint 200 by 140, walls 110 high, ridge 80 above them along x.
_HOUSE_AT = "translate(230 418)"
_HOUSE_LEFT = "0,0 -121.2,-70 -121.2,-180 -60.6,-225 0,-110"  # gable end
_HOUSE_RIGHT = "0,0 173.2,-100 173.2,-210 0,-110"
_HOUSE_ROOF = "0,-110 173.2,-210 112.6,-325 -60.6,-225"
_HOUSE_DOOR = "-65,-37.5 -99.6,-57.5 -99.6,-117.5 -65,-97.5"
_HOUSE_WINDOWS = (
    "43.3,-65 77.9,-85 77.9,-125 43.3,-105",
    "103.9,-100 138.6,-120 138.6,-160 103.9,-140",
)
_HOUSE_HIDDEN = (
    "M173.2,-100 L52,-170 L-121.2,-70 M52,-170 V-280",  # back floor edges, corner
    "M-121.2,-180 L52,-280 L112.6,-325",  # back eave on the back wall, far gable
    "M86.6,-50 L-34.6,-120 L-34.6,-230 M86.6,-50 V-160 L-34.6,-230",  # wall x=100
    "M-43.3,-25 L43.3,-75 L43.3,-185 M-43.3,-25 V-135 L43.3,-185",  # wall y=50
)


def house(c: dict[str, str], hidden: bool = False) -> str:
    """The isometric house, coloured by ``c``; ``hidden`` dashes its hidden edges."""
    faces = "".join(
        f'<polygon points="{points}" fill="{c[fill]}"/>'
        for points, fill in (
            (_HOUSE_LEFT, "f2"),
            (_HOUSE_RIGHT, "f1"),
            (_HOUSE_ROOF, "f0"),
        )
    )
    dashed = ""
    if hidden:
        dashed = (
            f'<g fill="none" stroke="{c["ink"]}" stroke-width="5" '
            f'stroke-dasharray="11 8">'
            + "".join(f'<path d="{d}"/>' for d in _HOUSE_HIDDEN)
            + "</g>"
        )
    openings = f'<polygon points="{_HOUSE_DOOR}" fill="{c["door"]}"/>' + "".join(
        f'<polygon points="{w}" fill="{c["win"]}"/>' for w in _HOUSE_WINDOWS
    )
    return (
        f'<g transform="{_HOUSE_AT}" stroke="{c["ink"]}" stroke-width="8" '
        f'stroke-linejoin="round">{faces}{dashed}'
        f'<g stroke="none">{openings}</g></g>'
    )


# Thermal Lab: the measured past as a sine wave, a dotted line for now, then
# the forecast: heat input raising the room most, the sun raising it gently,
# the cold outside pulling it down.
_LAB_NOW = "M256 124 V400"
_LAB_PAST = "M100 272 Q139 182 178 272 T256 272"
_LAB_COLD = "M256 272 C306 292 352 334 408 352"
_LAB_SOLAR = "M256 272 C304 232 356 214 408 236"
_LAB_HEAT = "M256 272 C300 246 344 196 404 158"


def thermal_lab(c: dict[str, str]) -> str:
    """The past wave and the three forecast curves, coloured by ``c``."""
    return (
        '<g fill="none" stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="{_LAB_NOW}" stroke="{c["past"]}" stroke-width="14" '
        'stroke-dasharray="1 30"/>'
        f'<path d="{_LAB_PAST}" stroke="{c["past"]}" stroke-width="30"/>'
        f'<path d="{_LAB_COLD}" stroke="{c["cold"]}" stroke-width="22"/>'
        f'<path d="{_LAB_SOLAR}" stroke="{c["solar"]}" stroke-width="22"/>'
        f'<path d="{_LAB_HEAT}" stroke="{c["heat"]}" stroke-width="22"/>'
        "</g>"
    )


# Manual J: a hardcover standing up, cover to the right (the y=0 plane, x 0 to
# 180, z 0 to 240), 48 thick. The boards overhang the page block, which sits 8
# lower, so a strip of the back board's inside shows above the pages. The
# spine is rounded, with two bands, and a hinge groove runs down the cover.
_BOOK_AT = "translate(199 433)"
_BOOK_BACK_TOP = "-32.9,-259 122.9,-349 114.3,-354 -41.6,-264"
_BOOK_BACK_INSIDE = "-32.9,-251 122.9,-341 122.9,-349 -32.9,-259"
_BOOK_PAGES = "-8.66,-237 140.3,-323 116.1,-337 -32.9,-251"
_BOOK_PAGE_LINES = (
    "M-11.3,-242.5 L130.8,-324.5 M-17.3,-246 L124.7,-328 M-23.4,-249.5 L118.7,-331.5"
)
_BOOK_FRONT_TOP = "0,-240 155.9,-330 147.2,-335 -8.66,-245"
_BOOK_COVER = "0,0 155.9,-90 155.9,-330 0,-240"
_BOOK_GROOVE = "M12.1,-7 V-247"
_BOOK_SPINE = "M0,0 Q-34.6,-4 -41.6,-24 V-264 Q-34.6,-244 0,-240 Z"
_BOOK_BANDS = "M0,-40 Q-34.6,-44 -41.6,-64 M0,-200 Q-34.6,-204 -41.6,-224"
_BOOK_TOP = "0,-240 155.9,-330 114.3,-354 -41.6,-264"  # the whole top, for mono
# The cover's own plane: u to the right along the cover, v down from its top
_BOOK_COVER_PLANE = "matrix(.866 -.5 0 1 0 -240)"
_BOOK_J = "M134 46 V140 A36 36 0 0 1 62 140"
_BOOK_RULE = "M64 210 H140"


def manual_j(c: dict[str, str]) -> str:
    """The hardcover with a J on it, coloured by ``c``."""
    ink = f'stroke="{c["ink"]}" stroke-width="5"'
    return (
        f'<g transform="{_BOOK_AT}" stroke-linejoin="round">'
        f'<polygon points="{_BOOK_BACK_TOP}" fill="{c["board"]}" {ink}/>'
        f'<polygon points="{_BOOK_BACK_INSIDE}" fill="{c["inner"]}" {ink}/>'
        f'<polygon points="{_BOOK_PAGES}" fill="{c["pages"]}" {ink}/>'
        f'<path d="{_BOOK_PAGE_LINES}" fill="none" stroke="{c["pageline"]}" '
        'stroke-width="3"/>'
        f'<polygon points="{_BOOK_FRONT_TOP}" fill="{c["board"]}" {ink}/>'
        f'<polygon points="{_BOOK_COVER}" fill="{c["cover"]}" {ink}/>'
        f'<path d="{_BOOK_GROOVE}" fill="none" stroke="{c["spine"]}" '
        'stroke-width="5"/>'
        f'<path d="{_BOOK_SPINE}" fill="{c["spine"]}" {ink}/>'
        f'<path d="{_BOOK_BANDS}" fill="none" stroke="{c["band"]}" '
        'stroke-width="8"/>'
        f'<g transform="{_BOOK_COVER_PLANE}" fill="none" stroke="{c["j"]}" '
        'stroke-linecap="round">'
        f'<path d="{_BOOK_J}" stroke-width="32"/>'
        f'<path d="{_BOOK_RULE}" stroke-width="9"/>'
        "</g></g>"
    )


MARKS = {"house": house, "thermal-lab": thermal_lab, "manual-j": manual_j}

# One-colour versions for the sidebar: outlines heavy enough for 24 px, the
# small detail left out. Each element carries its own transform (no groups),
# so Inkscape can turn every stroke into an outline and join them into one path.
_LINE = 'fill="none" stroke="#000" stroke-linejoin="round" stroke-linecap="round"'
MONO = {
    "house": "".join(
        f'<polygon transform="{_HOUSE_AT}" points="{p}" {_LINE} stroke-width="26"/>'
        for p in (_HOUSE_LEFT, _HOUSE_RIGHT, _HOUSE_ROOF)
    )
    + "".join(
        f'<polygon transform="{_HOUSE_AT}" points="{p}" fill="#000"/>'
        for p in (_HOUSE_DOOR, *_HOUSE_WINDOWS)
    ),
    "thermal-lab": (
        f'<path d="{_LAB_NOW}" {_LINE} stroke-width="22" stroke-dasharray="1 40"/>'
        f'<path d="{_LAB_PAST}" {_LINE} stroke-width="34"/>'
        + "".join(
            f'<path d="{d}" {_LINE} stroke-width="26"/>'
            for d in (_LAB_COLD, _LAB_SOLAR, _LAB_HEAT)
        )
    ),
    "manual-j": (
        f'<path transform="{_BOOK_AT}" d="{_BOOK_SPINE}" {_LINE} stroke-width="22"/>'
        f'<polygon transform="{_BOOK_AT}" points="{_BOOK_COVER}" {_LINE} '
        'stroke-width="22"/>'
        f'<polygon transform="{_BOOK_AT}" points="{_BOOK_TOP}" {_LINE} '
        'stroke-width="22"/>'
        f'<path transform="{_BOOK_AT} {_BOOK_COVER_PLANE}" d="{_BOOK_J}" {_LINE} '
        'stroke-width="34"/>'
    ),
    # A hallway in one-point perspective: the far wall with a door, the four
    # corners running out to the viewer, and a runner leading to the door.
    "room-hallway": (
        f'<rect x="150" y="140" width="212" height="210" {_LINE} stroke-width="26"/>'
        f'<path d="M150 140 L60 50 M362 140 L452 50 M150 350 L60 440 '
        f'M362 350 L452 440" {_LINE} stroke-width="26"/>'
        f'<path d="M210 350 V196 H302 V350" {_LINE} stroke-width="26"/>'
        f'<path d="M210 350 L178 440 M302 350 L334 440" {_LINE} stroke-width="26"/>'
        '<circle cx="282" cy="278" r="13" fill="#000"/>'
    ),
    # A double vanity: two mirrors over a counter, two basins set into it,
    # each with a gooseneck faucet arching over it.
    "double-sinks": (
        f'<rect x="92" y="50" width="140" height="130" rx="18" {_LINE} '
        'stroke-width="26"/>'
        f'<rect x="280" y="50" width="140" height="130" rx="18" {_LINE} '
        'stroke-width="26"/>'
        f'<path d="M48 330 H464" {_LINE} stroke-width="26"/>'
        f'<path d="M86 330 C86 385 116 412 162 412 C208 412 238 385 238 330" '
        f'{_LINE} stroke-width="26"/>'
        f'<path d="M274 330 C274 385 304 412 350 412 C396 412 426 385 426 330" '
        f'{_LINE} stroke-width="26"/>'
        f'<path d="M112 330 V264 A32 32 0 0 1 176 264 V282" {_LINE} '
        'stroke-width="26"/>'
        f'<path d="M300 330 V264 A32 32 0 0 1 364 264 V282" {_LINE} '
        'stroke-width="26"/>'
    ),
    # A bed from the side, solid: a tall headboard, the frame and the foot leg,
    # the sleeper's head and the blanket over them.
    "room-bedroom": (
        '<path d="M50 90 V400 M462 320 V400" fill="none" stroke="#000" '
        'stroke-width="36" stroke-linecap="round"/>'
        '<rect x="32" y="290" width="448" height="56" fill="#000"/>'
        '<circle cx="128" cy="212" r="46" fill="#000"/>'
        '<path d="M200 270 V170 Q200 150 220 150 H430 A50 50 0 0 1 480 200 V270 Z" '
        'fill="#000"/>'
    ),
}
# Icons in the set that are not an integration's mark.
EXTRA_ICONS = ("room-hallway", "double-sinks", "room-bedroom")

# The bedroom icons: the bed with a black disc over its foot, and a label cut
# out of the disc, as ``room-bedroom-<label>`` (in lower case).
BEDROOM_LABELS = (
    *("N", "NE", "E", "SE", "S", "SW", "W", "NW"),
    *"123456789",
    *("A", "D", "L", "J", "H"),
)
_BADGE = (396, 360, 116)  # centre x, centre y, radius
_BADGE_GAP = 22  # cleared around the disc
_BADGE_MARGIN = 14  # kept between a label's corners and the disc's edge
_BADGE_CAP = 128  # the tallest a label's capitals may be
ICON_FONT_WEIGHT = 800


# --- tools -------------------------------------------------------------------
def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise SystemExit(f"{name} is not on the path")
    return found


def _run(*args: str | Path) -> str:
    return subprocess.run(
        [str(a) for a in args], check=True, capture_output=True, text=True
    ).stdout


def svg(view_box: str, body: str, width: float, height: float) -> str:
    """A standalone SVG document."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" '
        f'width="{width:g}" height="{height:g}">{body}</svg>\n'
    )


def bbox(body: str, work: Path) -> tuple[float, float, float, float]:
    """The drawn extent of ``body`` on the canvas (strokes included): x, y, w, h."""
    path = work / "measure.svg"
    path.write_text(
        svg(f"0 0 {CANVAS} {CANVAS}", f'<g id="mark">{body}</g>', CANVAS, CANVAS),
        encoding="utf-8",
    )
    out = _run(
        _tool("inkscape"),
        "--query-id=mark",
        "--query-x",
        "--query-y",
        "--query-width",
        "--query-height",
        path,
    )
    x, y, w, h = (float(v) for v in out.split())
    return x, y, w, h


def square(box: tuple[float, float, float, float]) -> str:
    """A square viewBox around ``box``, centred on it."""
    x, y, w, h = box
    side = max(w, h)
    left, top = x + w / 2 - side / 2, y + h / 2 - side / 2
    return f"{left:.1f} {top:.1f} {side:.1f} {side:.1f}"


def png(source: Path, target: Path, *, width: int = 0, height: int = 0) -> None:
    """Render ``source`` to ``target`` at a width or height, then optimise it."""
    size = f"--export-width={width}" if width else f"--export-height={height}"
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(
        _tool("inkscape"),
        source,
        "--export-type=png",
        f"--export-filename={target}",
        "--export-background-opacity=0",
        size,
    )
    _run(_tool("optipng"), "-quiet", "-o5", "-i1", "-strip", "all", target)


# --- the name, outlined --------------------------------------------------------
class Lettering:
    """Outlines of text in the logo's typeface, kerned by HarfBuzz."""

    def __init__(self, font: Path, weight: int = FONT_WEIGHT) -> None:
        variable = TTFont(font)
        self.font = instancer.instantiateVariableFont(variable, {"wght": weight})
        data = io.BytesIO()
        self.font.save(data)
        self.shaper = hb.Font(hb.Face(hb.Blob(data.getvalue())))
        self.upem = self.font["head"].unitsPerEm
        self.cap = self.font["OS/2"].sCapHeight / self.upem
        self.glyphs = self.font.getGlyphSet()
        self.order = self.font.getGlyphOrder()

    def path(self, text: str, size: float, x: float, baseline: float) -> tuple:
        """The text's outline as path data, and its width, at ``size`` units."""
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(self.shaper, buffer, {"kern": True, "liga": True})
        scale = size / self.upem
        commands = []
        for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            pen = SVGPathPen(
                self.glyphs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
            )
            at = (
                scale, 0, 0, -scale,
                x + pos.x_offset * scale, baseline - pos.y_offset * scale,
            )  # fmt: skip
            self.glyphs[self.order[info.codepoint]].draw(TransformPen(pen, at))
            commands.append(pen.getCommands())
            x += pos.x_advance * scale
        return " ".join(c for c in commands if c), x


# --- the files -------------------------------------------------------------------
def write_brand(
    item: Integration,
    scheme: dict,
    lettering: Lettering,
    repo: Path,
    work: Path,
) -> list[Path]:
    """The icon and logo sources and PNGs for one integration; the files written."""
    written: list[Path] = []
    sources = repo / "brand"
    shipped = repo / "custom_components" / item.domain / "brand"
    sources.mkdir(exist_ok=True)
    draw = MARKS[item.icon]
    box = bbox(draw(scheme[item.icon]["light"]), work)
    x, y, w, h = box
    for theme, prefix in (("light", ""), ("dark", "dark_")):
        body = draw(scheme[item.icon][theme])
        # icon: the mark trimmed to a square
        icon = sources / f"{prefix}icon.svg"
        icon.write_text(svg(square(box), body, ICON_SIZE, ICON_SIZE), encoding="utf-8")
        png(icon, shipped / f"{prefix}icon.png", width=ICON_SIZE)
        png(icon, shipped / f"{prefix}icon@2x.png", width=ICON_SIZE * 2)
        # logo: the mark, then the name, centred on the mark's height
        height = 2 * LOGO_HEIGHT
        mark_width = height * w / h
        gap = 0.16 * height
        size = 0.40 * height / lettering.cap
        baseline = height / 2 + 0.40 * height / 2
        text, right = lettering.path(item.name, size, mark_width + gap, baseline)
        fill = scheme["text"][theme]["fill"]
        logo_body = (
            f'<svg x="0" y="0" width="{mark_width:.1f}" height="{height}" '
            f'viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}">{body}</svg>'
            f'<path fill="{fill}" d="{text}"/>'
        )
        logo = sources / f"{prefix}logo.svg"
        logo.write_text(
            svg(f"0 0 {right:.1f} {height}", logo_body, right / 2, LOGO_HEIGHT),
            encoding="utf-8",
        )
        png(logo, shipped / f"{prefix}logo.png", height=LOGO_HEIGHT)
        png(logo, shipped / f"{prefix}logo@2x.png", height=2 * LOGO_HEIGHT)
        written += [icon, logo]
        written += [
            shipped / f"{prefix}{kind}{scale}.png"
            for kind in ("icon", "logo")
            for scale in ("", "@2x")
        ]
    return written


def write_drafting(scheme: dict, repo: Path, work: Path) -> list[Path]:
    """The house with its hidden edges dashed, for the README and other large uses."""
    body = house(scheme["house"]["light"], hidden=True)
    target = repo / "brand" / "drafting.svg"
    target.write_text(svg(square(bbox(body, work)), body, 512, 512), encoding="utf-8")
    png(target, target.with_suffix(".png"), width=1024)
    return [target, target.with_suffix(".png")]


def mono(name: str, work: Path) -> tuple[str, str]:
    """One mark as a single filled path: its path data and a square viewBox."""
    data = one_path(
        name,
        MONO[name],
        "select-all:all;object-stroke-to-path;select-all:all;path-union",
        work,
    )
    return data, square(bbox(f'<path d="{data}"/>', work))


def one_path(name: str, body: str, actions: str, work: Path) -> str:
    """The path data Inkscape's ``actions`` leave of ``body``, which must be one."""
    source = work / f"{name}-strokes.svg"
    joined = work / f"{name}-joined.svg"
    source.write_text(
        svg(f"0 0 {CANVAS} {CANVAS}", body, CANVAS, CANVAS), encoding="utf-8"
    )
    _run(
        _tool("inkscape"),
        source,
        f"--actions={actions};"
        f"export-plain-svg;export-filename:{joined.as_posix()};export-do",
    )
    text = joined.read_text(encoding="utf-8")
    paths = re.findall(r"<path\b[^>]*>", text)
    if len(paths) != 1:
        raise SystemExit(f"{name}: Inkscape left {len(paths)} paths, not one")
    found = re.search(r'\sd="([^"]+)"', paths[0])
    assert found is not None
    data = found.group(1)
    moved = re.search(r'\stransform="([^"]+)"', paths[0])
    if moved:
        shift = re.fullmatch(r"translate\(\s*([-\d.e]+)[\s,]+([-\d.e]+)\s*\)", moved[1])
        if shift is None:
            raise SystemExit(f"{name}: Inkscape left a transform: {moved[1]}")
        data = translated(data, float(shift[1]), float(shift[2]))
    return " ".join(data.split())


def bedrooms(font: Path, work: Path) -> dict[str, tuple[str, str]]:
    """The bedroom icons by name: each one's path data and square viewBox.

    The disc is wound against the font's outer contours, so
    the label cuts through the disc and the letters' counters stay filled.
    """
    cx, cy, radius = _BADGE
    bed, _ = mono("room-bedroom", work)
    clear = circle_at(cx, cy, radius + _BADGE_GAP)
    cut = one_path(
        "bed-cut",
        f'<path d="{bed}"/><path d="{clear}"/>',
        "select-all:all;path-difference",
        work,
    )
    disc = (  # anticlockwise, against the letters
        f"M {cx:.2f} {cy - radius:.2f} "
        f"A {radius:.2f} {radius:.2f} 0 1 0 {cx:.2f} {cy + radius:.2f} "
        f"A {radius:.2f} {radius:.2f} 0 1 0 {cx:.2f} {cy - radius:.2f} Z"
    )
    view_box = square(bbox(f'<path d="{cut}"/><path d="{disc}"/>', work))
    letters = Lettering(font, ICON_FONT_WEIGHT)
    icons = {}
    for label in BEDROOM_LABELS:
        # As large as the label fits: its box's corners inside the disc
        width = letters.path(label, 1 / letters.cap, 0, 0)[1]  # per unit of cap
        cap = min(_BADGE_CAP, 2 * (radius - _BADGE_MARGIN) / math.hypot(width, 1))
        left = cx - width * cap / 2
        text, _ = letters.path(label, cap / letters.cap, left, cy + cap / 2)
        icons[f"room-bedroom-{label.lower()}"] = (f"{cut} {disc} {text}", view_box)
    return icons


_ARGS = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "A": 7}


def translated(data: str, dx: float, dy: float) -> str:
    """Path data moved by ``dx``, ``dy`` (absolute commands, as Inkscape writes)."""
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", data)
    out: list[str] = []
    command = ""
    values: list[float] = []

    def flush() -> None:
        n = _ARGS[command]
        for start in range(0, len(values), n):
            group = values[start : start + n]
            if command == "H":
                group[0] += dx
            elif command == "V":
                group[0] += dy
            elif command == "A":
                group[5] += dx
                group[6] += dy
            else:
                for i in range(0, n, 2):
                    group[i] += dx
                    group[i + 1] += dy
            out.append(" ".join(f"{v:.3f}".rstrip("0").rstrip(".") for v in group))

    for token in tokens:
        if token.isalpha():
            if command:
                flush()
            if token.islower() and token != "z":
                raise SystemExit(f"relative path command {token} not handled")
            command, values = token.upper(), []
            out.append(command)
            if command == "Z":
                command = ""
        else:
            values.append(float(token))
    if command:
        flush()
    return " ".join(out)


def _sun_sweep_icon() -> tuple[str, str]:
    """Line art of the Sun Sweep mark: ring, house outline, sun.

    A filled path with holes, so it reads as strokes in the one-colour icon
    set. Opposite windings cut the holes out.
    """
    cx = cy = 12.0

    def circle(radius: float, sweep: int) -> str:
        return (
            f"M {cx:.2f} {cy - radius:.2f} "
            f"A {radius:.2f} {radius:.2f} 0 1 {sweep} {cx:.2f} {cy + radius:.2f} "
            f"A {radius:.2f} {radius:.2f} 0 1 {sweep} {cx:.2f} {cy - radius:.2f} Z"
        )

    def point(east: float, north: float, scale: float = 3.5) -> tuple[float, float]:
        return cx + east * scale, cy - north * scale

    def polygon(points: list[tuple[float, float]]) -> str:
        x, y = points[0]
        drawing = f"M {x:.2f} {y:.2f}"
        for x, y in points[1:]:
            drawing += f" L {x:.2f} {y:.2f}"
        return drawing + " Z"

    outer = [(-1, -0.7), (1, -0.7), (1, 0.15), (0.1, 0.15), (0.1, 0.7), (-1, 0.7)]
    inset = 0.28
    inner = [
        (-1 + inset, -0.7 + inset),
        (1 - inset, -0.7 + inset),
        (1 - inset, 0.15 - inset),
        (0.1 - inset, 0.15 - inset),
        (0.1 - inset, 0.7 - inset),
        (-1 + inset, 0.7 - inset),
    ]
    turn = math.radians(108)
    sun_r = 2.15
    # The sun rides the middle of the ring, as it does in the logo.
    ride = (10.2 + 8.35) / 2
    sun = (cx + ride * math.sin(turn), cy - ride * math.cos(turn))
    path = " ".join(
        [
            circle(10.2, 1),
            circle(8.35, 0),
            polygon([point(*corner) for corner in outer]),
            polygon([point(*corner) for corner in reversed(inner)]),
            circle_at(*sun, sun_r),
        ]
    )
    return path, "0 0 24 24"


def circle_at(cx: float, cy: float, radius: float) -> str:
    """A filled disc as two arcs."""
    return (
        f"M {cx:.2f} {cy - radius:.2f} "
        f"A {radius:.2f} {radius:.2f} 0 1 1 {cx:.2f} {cy + radius:.2f} "
        f"A {radius:.2f} {radius:.2f} 0 1 1 {cx:.2f} {cy - radius:.2f} Z"
    )


def write_icon_set(repo: Path, work: Path, font: Path) -> list[Path]:
    """The one-colour sidebar icons, as SVGs and as a Home Assistant icon set."""
    folder = repo / "brand" / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    drawn = {
        name: mono(name, work)
        for name in (*(item.icon for item in INTEGRATIONS), *EXTRA_ICONS)
    }
    drawn["sun-sweep"] = _sun_sweep_icon()
    drawn |= bedrooms(font, work)
    icons = {}
    written = []
    for name, (data, view_box) in drawn.items():
        icons[name] = {"path": data, "viewBox": view_box}
        target = folder / f"{name}.svg"
        target.write_text(
            svg(view_box, f'<path d="{data}"/>', 24, 24), encoding="utf-8"
        )
        written.append(target)
    names = textwrap.wrap(
        ", ".join(f'"{ICON_PREFIX}:{name}"' for name in icons),
        76,
        break_on_hyphens=False,
    )
    script = repo / "custom_components" / "house_structure" / "frontend" / "icons.js"
    script.write_text(
        "// Generated by scripts/brand.py: do not edit by hand.\n"
        "// The house integrations' icons, as a Home Assistant icon set: use\n"
        + "".join(f"//   {line}\n" for line in names)
        + "// wherever an icon name goes (the sidebar, a dashboard card).\n"
        f"const ICONS = {json.dumps(icons, indent=2)};\n\n"
        "window.customIcons = window.customIcons || {};\n"
        f'window.customIcons["{ICON_PREFIX}"] = {{\n'
        '  getIcon: async (name) => ICONS[name] || { path: "" },\n'
        "  getIconList: async () => Object.keys(ICONS).map((name) => ({ name })),\n"
        "};\n",
        encoding="utf-8",
        newline="\n",
    )
    written.append(script)
    return written


def main() -> None:
    """Write the brand files for the chosen integrations."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--font", type=Path, default=FONT, help="Figtree's variable TTF"
    )
    parser.add_argument("--scheme", choices=sorted(SCHEMES), default="drawing")
    parser.add_argument(
        "--repos",
        type=Path,
        default=ROOT.parent,
        help="the folder holding the three repositories (default: this one's parent)",
    )
    parser.add_argument(
        "--only",
        choices=[i.domain for i in INTEGRATIONS],
        action="append",
        help="only this integration (may be given more than once)",
    )
    args = parser.parse_args()
    scheme = SCHEMES[args.scheme]
    lettering = Lettering(args.font)
    written: list[Path] = []
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        for item in INTEGRATIONS:
            if args.only and item.domain not in args.only:
                continue
            repo = ROOT if item.repo == ROOT.name else args.repos / item.repo
            if not (repo / "custom_components" / item.domain).is_dir():
                print(f"skipped {item.name}: no {repo / 'custom_components'}")
                continue
            written += write_brand(item, scheme, lettering, repo, work)
            if item.domain == "house_structure":
                written += write_drafting(scheme, repo, work)
                written += write_icon_set(repo, work, args.font)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
