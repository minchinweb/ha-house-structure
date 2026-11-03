# House Structure

A Home Assistant integration that describes your house once: its rooms, outside
walls, roofs, windows, internal walls and heating registers. The rooms are Home
Assistant's areas, and each part of the house is a device in its room's area,
with sensors for the sun on it, the solar heat through each window (less what
its blind keeps out), the temperature difference across internal walls and
whether each register is heating.

Other integrations can then read a room's parts by its area instead of asking
for them again. [Home Thermal Lab](https://github.com/minchinweb/ha-home-thermal-lab)
uses it for each zone's windows, roofs, sunlit walls, thermostat and room
temperature sensor.

## Installation

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=minchinweb&repository=ha-house-structure&category=integration)

1. Click the button above. It opens this repository in HACS (the Marketplace
   in Home Assistant 2026.11 and later) on your own Home Assistant. If asked,
   confirm adding it as a custom repository.
2. Click **Download**, then restart Home Assistant.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=house_structure)

Without HACS, copy `custom_components/house_structure/` into Home Assistant's
`custom_components/` folder and restart.

It needs Home Assistant 2025.3 or later. By default it fetches the sun and sky
light every 15 minutes from [Open-Meteo](https://open-meteo.com/) for the home
location (no key needed); it can read a solar radiation sensor instead (see
**Sky source** below). It switches nothing.

## Setting up the house

First set what is true of the whole house:

- **House rotation**: degrees the house is turned clockwise from true north.
  Its four faces then look this far past north, east, south and west.
- **Shaded below sun elevation**: trees and neighbours to the south block the
  sun's beam below this height (from south-east to south-west).
- **Unit for sizes**: the unit you measured in. Sizes are kept in metres, so
  changing the unit later keeps them.
- **Sky source**: where the light comes from.
  - **Open-Meteo** (the default): fetched over the internet every 15 minutes.
  - **Solar radiation sensor**: a sensor reading all the light on a flat
    surface in W/m², such as a weather station's. It is read every 5 minutes
    and split into the sun's beam and the light from the rest of the sky (the
    Erbs model), so it needs no internet. The split is an estimate, and the
    sensor must be out of shade.

The sun's position comes from `astral`, the library behind Home Assistant's
`sun.sun`, worked out for the middle of each reading.

Then add the parts from the integration's page. Each asks for its room (area);
a window instead asks for the wall or roof it is in and takes its room and the
way it faces from there.

| Part | Settings | Sensor |
|---|---|---|
| Room (one per area) | floor area, ceiling height, volume (for a sloped ceiling), below ground | solar gain through all its windows (W) |
| Outside wall | face, length, height | sun on it (W/m²) |
| Roof | face, pitch (`45` or `12:12`), length along the eave, slope length | sun on it (W/m²) |
| Window | the wall or roof it is in, glass size, share let in as heat, blind (a cover) | solar gain (W), less what the blind keeps out |
| Internal wall | the room on the other side, length, height | this room minus the other (°C) |
| Heating register | thermostat, its fan or damper | heating (on while the thermostat heats) |

A part not square to the house can give its own compass bearing (**Facing**). A
blind is read from its cover's position (0 shut to 100 open); **Share let in
with the blind closed** is how much sun still gets through it shut. The internal
wall uses the temperature sensor chosen in each area's settings, or the area's
only temperature sensor.

Each sensor's attributes give the part's geometry: compass azimuth, tilt, areas
in m², the window's wall or roof and the rooms on each side.

## For other integrations

House Structure publishes each room's parts as plain data in
`hass.data["house_structure"]`:

```python
{
    "version": 1,
    "rooms": {
        "master_bedroom": {  # the area id
            "area_id": "master_bedroom",
            "title": "Room",
            "floor_m2": 11.6,
            "height_m": 2.4,
            "volume_m3": 28.3,
            "below_ground": False,
            "temperature_entity": "sensor.master_temperature",
            "windows": [
                {
                    "title": "South window",
                    "azimuth": 190.4,
                    "tilt": 90.0,
                    "shade_below": 0.0,
                    "in": "wall",
                    "glass_m2": 1.70,
                    "transmittance": 0.7,
                    "blind": "cover.master_blinds",
                    "blind_closed": 0.2,
                }
            ],
            "walls": [
                {
                    "title": "South wall",
                    "azimuth": 190.4,
                    "tilt": 90.0,
                    "shade_below": 0.0,
                    "area_m2": 5.8,
                    "glass_m2": 1.70,
                }
            ],
            "roofs": [...],  # as walls
            "internal_walls": [
                {
                    "title": "Wall to Upstairs bath",
                    "other_area_id": "upstairs_bath",
                    "area_m2": None,
                }
            ],
            "registers": [
                {
                    "title": "Register",
                    "climate": "climate.z3",
                    "fan": "fan.master_register",
                }
            ],
        },
    },
}
```

Every area with a part is a room. When the rooms change, it fires the
`house_structure_updated` event. Add `"after_dependencies": ["house_structure"]`
to your manifest so it is set up first. The `version` goes up only when a key
changes meaning or goes away.

## Development

```
uv sync
uv run invoke check
```

The tests use Home Assistant's own test harness, which needs Linux; on Windows,
run them under WSL with a Linux-side environment:

```
UV_PROJECT_ENVIRONMENT=$HOME/venvs/ha-house-structure uv run pytest
```
