# Copyright (c) 2026 MinchinWeb
"""Names shared by the integration's modules (standard library only)."""

from __future__ import annotations

DOMAIN = "house_structure"
PLATFORMS = ["binary_sensor", "sensor"]

# Sub-entry types: one per kind of part.
WALL = "wall"
ROOF = "roof"
WINDOW = "window"
INTERNAL_WALL = "internal_wall"
ROOM = "room"
REGISTER = "register"

# Fired when the rooms' parts change, for integrations that use them.
UPDATED_EVENT = "house_structure_updated"
