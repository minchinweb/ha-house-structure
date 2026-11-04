# Copyright (c) 2026 MinchinWeb
"""The vendored scripts match their pins (``invoke vendor`` fetches them)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FRONTEND = Path("custom_components/house_structure/frontend")


def test_vendored_files_match_their_pins():
    pins = json.loads((FRONTEND / "vendor.json").read_text(encoding="utf-8"))
    assert pins
    for name, pin in pins.items():
        body = (FRONTEND / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == pin["sha256"], name
        assert pin["version"] in pin["url"]


def test_the_pages_fetch_nothing_from_the_internet():
    for page in FRONTEND.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        for tag in text.split("<script")[1:]:
            assert "https://" not in tag.split(">", 1)[0], page.name
