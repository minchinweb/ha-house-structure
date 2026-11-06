# Copyright (c) 2026 MinchinWeb
"""Render house drawings locally through the real placement and SVG paths.

No Home Assistant needed. Uses ``build`` → ``_place`` → ``house_svg`` the same
way the Thermal Lab plan does.

Examples::

    uv run python scripts/render_local.py
    uv run python scripts/render_local.py kitchen-face --view 1 --png
    uv run python scripts/render_local.py --from-diagnostics house.json -o out/

Scenarios:
  kitchen-face  Kitchen east face shared by outside window, open entrance, bath
  hall-hub      Several rooms packing flush around a hall
  sample-house  Multi-room facsimile; ground floor left untyped so the packer runs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.house_structure.constants import (  # noqa: E402
    INTERNAL_WALL,
    REGISTER,
    ROOF,
    ROOM,
    WALL,
    WINDOW,
)
from custom_components.house_structure.drawing import (  # noqa: E402
    VIEWS,
    _place,
    _shared_face,
    house_svg,
)
from custom_components.house_structure.model import Raw, build  # noqa: E402

# house settings, parts, area→floor level, pairs to check for shared faces
Scenario = tuple[dict, list[Raw], dict[str, int], list[tuple[str, str]]]

HOUSE = {
    "rotation": 12.0,
    "unit": "m",
    "shade_below": 0.0,
    "plenum_x_m": 8.0,
    "plenum_y_m": 3.0,
    "plenum_z_m": -0.5,
}


def room(area: str, **data) -> Raw:
    return Raw(
        f"room-{area}",
        ROOM,
        area.replace("_", " ").title(),
        {"area_id": area, **data},
    )


def wall(uid: str, area: str, face: str, length: float = 4.0, **data) -> Raw:
    return Raw(
        uid,
        WALL,
        f"{face} wall",
        {
            "area_id": area,
            "face": face,
            "length_m": length,
            "height_m": 2.4,
            **data,
        },
    )


def window(uid: str, host: str) -> Raw:
    return Raw(uid, WINDOW, "Window", {"host": host, "width_m": 1.2, "height_m": 1.2})


def roof(uid: str, areas: list[str], face: str, pitch: float = 30.0) -> Raw:
    return Raw(
        uid,
        ROOF,
        f"{face} roof",
        {"area_ids": areas, "face": face, "pitch": pitch},
    )


def iw(uid: str, a: str, b: str, open_link: bool = False) -> Raw:
    data = {"area_id": a, "other_area_id": b}
    if open_link:
        data["open"] = True
    return Raw(uid, INTERNAL_WALL, f"Wall {a}/{b}", data)


def reg(uid: str, area: str, title: str) -> Raw:
    return Raw(uid, REGISTER, title, {"area_id": area, "climate": "climate.z1"})


def scenario_kitchen_face() -> Scenario:
    """Kitchen E face: outside window stretch + open entrance + bath."""
    raws = [
        room("kitchen", width_m=4.5, depth_m=4.0, height_m=2.4, open=["entrance"]),
        wall("k_e", "kitchen", "E", 1.5),
        wall("k_s", "kitchen", "S", 4.5),
        wall("k_n", "kitchen", "N", 4.5),
        wall("k_w", "kitchen", "W", 4.0),
        window("k_e_win", "k_e"),
        room("entrance", width_m=2.0, depth_m=1.5, height_m=2.4),
        wall("en_e", "entrance", "E", 1.5),
        wall("en_s", "entrance", "S", 2.0),
        iw("k_en", "kitchen", "entrance", open_link=True),
        room("bath", width_m=2.0, depth_m=2.0, height_m=2.4),
        wall("b_e", "bath", "E", 2.0),
        iw("k_bath", "kitchen", "bath"),
    ]
    checks = [("kitchen", "entrance"), ("kitchen", "bath")]
    floors = {"kitchen": 0, "entrance": 0, "bath": 0}
    return HOUSE, raws, floors, checks


def scenario_hall_hub() -> Scenario:
    raws = [
        room("hall", width_m=2.0, depth_m=6.0, height_m=2.4, room_type="hallway"),
        wall("h_n", "hall", "N", 2.0),
        wall("h_s", "hall", "S", 2.0),
        room("kitchen", width_m=4.0, depth_m=3.5, height_m=2.4),
        wall("k_w", "kitchen", "W", 3.5),
        wall("k_s", "kitchen", "S", 4.0),
        iw("h_k", "hall", "kitchen"),
        room("living", width_m=4.5, depth_m=4.0, height_m=2.4),
        wall("l_e", "living", "E", 4.0),
        wall("l_n", "living", "N", 4.5),
        iw("h_l", "hall", "living"),
        room("office", width_m=3.0, depth_m=3.0, height_m=2.4),
        wall("o_w", "office", "W", 3.0),
        iw("h_o", "hall", "office"),
    ]
    floors = dict.fromkeys(("hall", "kitchen", "living", "office"), 0)
    checks = [
        ("hall", "kitchen"),
        ("hall", "living"),
        ("hall", "office"),
    ]
    return HOUSE, raws, floors, checks


def scenario_sample_house() -> Scenario:
    """Screenshot facsimile: ground floor untyped so the packer seats rooms."""
    raws = [
        room("garage", width_m=5.0, depth_m=6.0, height_m=2.4),
        wall("g_w", "garage", "W", 6.0),
        wall("g_s", "garage", "S", 5.0),
        wall("g_n", "garage", "N", 5.0),
        window("g_w_win", "g_w"),
        roof("g_roof", ["garage"], "W", 18.0),
        room("mud", width_m=2.0, depth_m=2.5, height_m=2.4),
        iw("g_mud", "garage", "mud"),
        room(
            "kitchen",
            width_m=4.5,
            depth_m=4.0,
            height_m=2.4,
            open=["entrance"],
        ),
        wall("k_e", "kitchen", "E", 1.5),
        wall("k_s", "kitchen", "S", 4.5),
        wall("k_n", "kitchen", "N", 4.5),
        wall("k_w", "kitchen", "W", 4.0),
        window("k_e_win", "k_e"),
        window("k_s_win", "k_s"),
        iw("mud_k", "mud", "kitchen"),
        iw("k_bath", "kitchen", "bath"),
        room("bath", width_m=2.0, depth_m=2.0, height_m=2.4),
        wall("b_e", "bath", "E", 2.0),
        room("entrance", width_m=2.0, depth_m=1.5, height_m=2.4),
        wall("en_e", "entrance", "E", 1.5),
        wall("en_s", "entrance", "S", 2.0),
        room(
            "hall",
            width_m=2.0,
            depth_m=5.5,
            height_m=2.4,
            room_type="hallway",
        ),
        iw("k_hall", "kitchen", "hall"),
        room("dining", width_m=3.5, depth_m=3.5, height_m=2.4),
        wall("d_s", "dining", "S", 3.5),
        wall("d_e", "dining", "E", 3.5),
        window("d_s_win", "d_s"),
        iw("hall_d", "hall", "dining"),
        room("living", width_m=5.0, depth_m=4.5, height_m=2.4),
        wall("l_e", "living", "E", 4.5),
        wall("l_n", "living", "N", 5.0),
        wall("l_s", "living", "S", 5.0),
        window("l_e_win", "l_e"),
        window("l_n_win", "l_n"),
        iw("hall_l", "hall", "living"),
        iw("d_l", "dining", "living"),
        roof(
            "main_s",
            ["kitchen", "dining", "living", "hall", "bath", "entrance", "mud"],
            "S",
            28.0,
        ),
        roof(
            "main_n",
            ["kitchen", "dining", "living", "hall", "bath", "entrance", "mud"],
            "N",
            28.0,
        ),
        room(
            "landing",
            width_m=2.0,
            depth_m=3.0,
            height_m=2.4,
            level_m=2.7,
            x_m=13.5,
            y_m=5.0,
            room_type="stairs",
        ),
        room(
            "bedroom",
            width_m=4.0,
            depth_m=4.0,
            height_m=2.4,
            level_m=2.7,
            x_m=15.5,
            y_m=5.5,
        ),
        wall("br_e", "bedroom", "E", 4.0),
        wall("br_n", "bedroom", "N", 4.0),
        wall("br_s", "bedroom", "S", 4.0),
        window("br_e_win", "br_e"),
        iw("land_br", "landing", "bedroom"),
        room(
            "ensuite",
            width_m=2.0,
            depth_m=2.5,
            height_m=2.4,
            level_m=2.7,
            x_m=19.5,
            y_m=5.5,
        ),
        wall("es_e", "ensuite", "E", 2.5),
        iw("br_es", "bedroom", "ensuite"),
        roof("up_s", ["landing", "bedroom", "ensuite"], "S", 35.0),
        roof("up_n", ["landing", "bedroom", "ensuite"], "N", 35.0),
        reg("r1", "garage", "Garage register"),
        reg("r2", "kitchen", "Kitchen register"),
        reg("r3", "living", "Living register"),
        reg("r4", "dining", "Dining register"),
        reg("r5", "bedroom", "Bedroom register"),
    ]
    floors = {
        a: (1 if a in {"landing", "bedroom", "ensuite"} else 0)
        for a in (
            "garage",
            "mud",
            "kitchen",
            "bath",
            "entrance",
            "hall",
            "dining",
            "living",
            "landing",
            "bedroom",
            "ensuite",
        )
    }
    checks = [
        ("garage", "mud"),
        ("mud", "kitchen"),
        ("kitchen", "bath"),
        ("kitchen", "entrance"),
        ("kitchen", "hall"),
        ("hall", "living"),
        ("hall", "dining"),
        ("landing", "bedroom"),
    ]
    return HOUSE, raws, floors, checks


SCENARIOS = {
    "kitchen-face": scenario_kitchen_face,
    "hall-hub": scenario_hall_hub,
    "sample-house": scenario_sample_house,
}


def from_diagnostics(path: Path) -> Scenario:
    """Load a ``house_structure/layout`` or diagnostics JSON dump."""
    data = json.loads(path.read_text(encoding="utf-8"))
    house = dict(data.get("house") or HOUSE)
    raws = [
        Raw(p["id"], p["kind"], p["title"], dict(p.get("settings") or {}))
        for p in data.get("parts") or []
    ]
    floors: dict[str, int] = {}
    for area in data.get("areas") or []:
        name = area.get("floor")
        area_id = area.get("area_id")
        if not area_id:
            continue
        # diagnostics only has floor names; map common labels, else 0
        level = 0
        if name and "up" in str(name).lower():
            level = 1
        elif name and ("base" in str(name).lower() or "down" in str(name).lower()):
            level = -1
        floors[area_id] = level
    rooms = [r for r in raws if r.kind == ROOM]
    checks = []
    for r in rooms:
        for other in r.data.get("beside") or []:
            checks.append((r.data["area_id"], other))
    return house, raws, floors, checks


def report_placement(
    elements: dict,
    house: dict,
    floors: dict[str, int],
    checks: list[tuple[str, str]],
    view: int,
) -> list:
    boxes, notes = _place(
        elements,
        house.get("unit", "m"),
        floors,
        house.get("rotation", 0.0),
        view,
    )
    at = {b.area: b for b in boxes}
    print(f"Placed {len(boxes)} rooms (view={VIEWS[view % 4]}):")
    for b in sorted(boxes, key=lambda x: (x.z, x.y, x.x)):
        print(
            f"  {b.area:12} x={b.x:6.2f} y={b.y:6.2f} "
            f"w={b.width:5.2f} d={b.depth:5.2f} z={b.z:5.2f}"
        )
    if checks:
        print("Shared faces:")
        for a, b in checks:
            if a not in at or b not in at:
                print(f"  {a}-{b}: missing box")
                continue
            shared = _shared_face(at[a], at[b])
            print(f"  {a}-{b}: {shared[0] if shared else 'GAP'}")
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  - {note}")
    return boxes


def maybe_png(svg_path: Path, dpi: int = 160) -> Path | None:
    inkscape = shutil.which("inkscape")
    if not inkscape:
        for candidate in (
            Path(r"C:\Program Files\Inkscape\bin\inkscape.exe"),
            Path("/usr/bin/inkscape"),
        ):
            if candidate.is_file():
                inkscape = str(candidate)
                break
    if not inkscape:
        print("Inkscape not found; skipping PNG")
        return None
    png = svg_path.with_suffix(".png")
    subprocess.run(
        [inkscape, str(svg_path), "-o", str(png), "-d", str(dpi)],
        check=True,
    )
    print(f"wrote {png}")
    return png


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        nargs="?",
        default="kitchen-face",
        choices=[*SCENARIOS, "diagnostics"],
        help="Built-in layout to render (default: kitchen-face)",
    )
    parser.add_argument(
        "--from-diagnostics",
        type=Path,
        help="JSON from house_structure/layout or config-entry diagnostics",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("out"),
        help="Output directory",
    )
    parser.add_argument("--view", type=int, default=1, help="0=SW 1=NW 2=NE 3=SE")
    parser.add_argument(
        "--exploded",
        action="store_true",
        help="Pull floors apart",
    )
    parser.add_argument(
        "--png",
        action="store_true",
        help="Also export PNG via Inkscape",
    )
    parser.add_argument("--dpi", type=int, default=160)
    args = parser.parse_args()

    if args.from_diagnostics:
        house, raws, floors, checks = from_diagnostics(args.from_diagnostics)
        name = args.from_diagnostics.stem
    else:
        if args.scenario == "diagnostics":
            parser.error("diagnostics scenario needs --from-diagnostics")
        house, raws, floors, checks = SCENARIOS[args.scenario]()
        name = args.scenario

    elements, problems = build(house, raws)
    if problems:
        print("Build skipped parts:")
        for problem in problems:
            print(f"  - {problem}")

    report_placement(elements, house, floors, checks, args.view)
    svg = house_svg(
        elements,
        house,
        exploded=args.exploded,
        view=args.view,
        floors=floors,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    svg_path = args.out / f"{name}_v{args.view}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    print(f"wrote {svg_path.resolve()}")
    if args.png:
        maybe_png(svg_path, args.dpi)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
