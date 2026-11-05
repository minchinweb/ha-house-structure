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
# What a room is, for the openings it has by default (``config_flow.py``).
ROOM_TYPE = "room"
HALLWAY = "hallway"
STAIRS = "stairs"
ROOM_TYPES = (ROOM_TYPE, HALLWAY, STAIRS)
# Rooms that open onto the rooms beside them unless a sheet says otherwise.
OPEN_ROOM_TYPES = (HALLWAY, STAIRS)
# Equipment and detached buildings (``equipment.py``): not surfaces or rooms.
FURNACE = "furnace"
AIR_CONDITIONER = "air_conditioner"
BUILDING = "building"
EQUIPMENT_KINDS = (FURNACE, AIR_CONDITIONER, BUILDING)

# Where the sky's light comes from (the house's ``sky_source``).
OPEN_METEO = "open_meteo"
SENSOR = "sensor"
SKY_SOURCES = [OPEN_METEO, SENSOR]

# Where the house form keeps the building outline it fetched from OpenStreetMap
# (``hass.data[DOMAIN]`` holds the published rooms).
OUTLINE = f"{DOMAIN}_outline"
# The file the building outline is kept in, so it works offline.
OUTLINE_STORE = f"{DOMAIN}.outline"

# Fired when the rooms' parts change, for integrations that use them.
UPDATED_EVENT = "house_structure_updated"

# The Thermal Lab page in the sidebar, which other integrations add tabs to
# (see ``panel.py``).
TABS = f"{DOMAIN}_tabs"
TABS_EVENT = f"{DOMAIN}_tabs_updated"
# What other integrations draw over the House tab's drawing (see ``tabs.py``).
OVERLAYS = f"{DOMAIN}_overlays"
OVERLAYS_EVENT = f"{DOMAIN}_overlays_updated"

# What other integrations need from the house, so a missing size raises a
# repair only when something uses it (see ``issues.py``).
NEEDS = f"{DOMAIN}_needs"
NEEDS_EVENT = f"{DOMAIN}_needs_updated"
