# Copyright (c) 2026 MinchinWeb
"""Names shared by the integration's modules (standard library only)."""

from __future__ import annotations

DOMAIN = "house_structure"
PLATFORMS = ["binary_sensor", "sensor"]

# Sub-entry types: one per kind of part.
WALL = "wall"
ROOF = "roof"
WINDOW = "window"
DOOR = "door"
INTERNAL_WALL = "internal_wall"
ROOM = "room"
REGISTER = "register"

# Where the sky's light comes from (the house's ``sky_source``).
OPEN_METEO = "open_meteo"
SENSOR = "sensor"
SKY_SOURCES = [OPEN_METEO, SENSOR]

# Where the house form keeps the building outline it fetched from OpenStreetMap
# (``hass.data[DOMAIN]`` holds the published rooms).
OUTLINE = f"{DOMAIN}_outline"

# Fired when the rooms' parts change, for integrations that use them.
UPDATED_EVENT = "house_structure_updated"
