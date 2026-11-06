# Copyright (c) 2026 MinchinWeb
"""Invoke tasks; run with ``uv run invoke --list``."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

from invoke import task

try:
    from minchin.tasks import (  # noqa: F401
        check,
        format_code,
        lint,
        test,
        update,
        upgrade,
    )
except ImportError:
    print("[WARN] minchin.tasks not installed.")

try:
    from minchin.releaser import make_release  # noqa: F401
except ImportError:
    print("[WARN] minchin.releaser not installed.")


FRONTEND = Path("custom_components/house_structure/frontend")


@task(
    help={
        "scenario": "kitchen-face, hall-hub, or sample-house",
        "view": "0=SW 1=NW 2=NE 3=SE",
        "png": "Also export a PNG with Inkscape when available",
        "diagnostics": "Path to a house_structure/layout or diagnostics JSON dump",
    }
)
def render(ctx, scenario="kitchen-face", view=1, png=False, diagnostics=""):
    """Render a house plan locally through the real drawing code (no HA)."""
    cmd = ["uv", "run", "python", "scripts/render_local.py"]
    if diagnostics:
        cmd.extend(["--from-diagnostics", diagnostics])
    else:
        cmd.append(scenario)
    cmd.extend(["--view", str(view), "-o", "out"])
    if png:
        cmd.append("--png")
    ctx.run(" ".join(cmd), pty=False)


@task(help={"check": "Only compare the files with their pins; download nothing."})
def vendor(ctx, check=False):
    """Fetch the Thermal Lab page's pinned scripts (Chart.js) into the integration.

    The pins (version, URL, SHA-256) are in `frontend/vendor.json`. The files
    are committed, so HACS installs them and Home Assistant serves them itself:
    opening the page fetches nothing from the internet. Every tab's page loads
    Chart.js from here. To upgrade, change the version and URL, run this with a
    blank `sha256` to see the new hash, check it, and pin it; then check the
    other integrations' tabs still draw.
    """
    pins = json.loads((FRONTEND / "vendor.json").read_text(encoding="utf-8"))
    failed = []
    for name, pin in pins.items():
        target = FRONTEND / name
        if check:
            body = target.read_bytes() if target.exists() else b""
        else:
            with urllib.request.urlopen(pin["url"], timeout=60) as response:
                body = response.read()
        digest = hashlib.sha256(body).hexdigest()
        if digest != pin["sha256"]:
            failed.append(f"{name}: sha256 {digest}, pinned {pin['sha256'] or '-'}")
            continue
        if not check:
            target.write_bytes(body)
        print(f"{name}: {pin['package']} {pin['version']} OK")
    if failed:
        raise SystemExit("; ".join(failed))
