# House Structure

A Home Assistant integration that describes your house once: its rooms, outside
walls, roofs, windows, doors, internal walls and heating registers. The rooms
are Home Assistant's areas, and each part of the house is a device in its room's
area, with a solar exposure sensor for it, the solar heat through each window
(less what its blind keeps out), whether each door is open, the temperature
difference across internal walls and whether each register is heating.

Other integrations can then read a room's parts by its area instead of asking
for them again. [Home Thermal Lab](https://github.com/minchinweb/ha-home-thermal-lab)
uses it for each zone's windows, roofs, sunlit walls, thermostat and room
temperature sensor.

It also adds the **Thermal Lab** page to the sidebar. House Structure's own
tab there, **House**, draws the house; other integrations add their own tabs
to the same page.

## Installation

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=minchinweb&repository=ha-house-structure&category=integration)

1. Click the button above. It opens this repository in the Marketplace
   (**Settings > Marketplace**, Home Assistant 2026.11 and later) on your own
   Home Assistant. It's a custom repository, so the Marketplace first asks
   you to connect GitHub, if you haven't (it reads public repositories
   only), and to confirm adding it. By hand: choose **Add from link** in the
   Marketplace and enter `https://github.com/minchinweb/ha-house-structure`.
2. Click **Install**. Restart Home Assistant if the Marketplace says to.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=house_structure)

Before Home Assistant 2026.11, install it with
[HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=minchinweb&repository=ha-house-structure&category=integration)
instead (download it, then restart Home Assistant). Without either, copy
`custom_components/house_structure/` into Home Assistant's `custom_components/`
folder and restart. Until that restart Home Assistant doesn't know House Structure is
there, and the **Add integration** link says it "does not support
configuration via the UI".

It needs Home Assistant 2025.3 or later. By default it fetches the sun and sky
light every 15 minutes from [Open-Meteo](https://open-meteo.com/) for the home
location (no key needed); it can read a solar radiation sensor instead (see
**Sky source** below). It switches nothing.

## Setting up the house

First set what is true of the whole house:

- **House rotation**: degrees the house is turned clockwise from true north.
  Its four faces then look this far past north, east, south and west. The
  form measures it from your building's outline on OpenStreetMap and draws
  the outline with the turned compass cross on it, so you can check it. To see
  another value, type it, tick **Redraw the map** and press Submit; nothing is
  saved until you submit with the box unticked.
- **Shaded below sun elevation**: trees and neighbours to the south block the
  sun's beam below this height (from south-east to south-west).
- **Unit for sizes**: the unit you measured in. Sizes are kept in metres, so
  changing the unit later keeps them. In **Feet and inches**, type lengths
  as `12' 6"`, `12'-6 1/2"`, `12 6` (feet, then inches) or `150"`; floor
  areas and volumes are in square and cubic feet.

  Whatever the unit, a size typed with its own unit is read in that one, so
  measurements can be mixed: `3.2 m`, `320 cm`, `12' 6"`, `12 ft 6 in`,
  `150"` for lengths; `14 m²`, `14 m2`, `150 sq ft`, `150 ft^2` for floor
  areas; `40 m³`, `1400 cu ft` for volumes. A bare number is in the house's
  unit. Editing a part shows its sizes back in the house's unit.
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
a roof asks for every room under it, since one roof often covers several. A
window instead asks for the wall or roof it is in and takes its room and the
way it faces from there; a skylight in a roof over several rooms can name the
one it lights. A door asks for the outside or internal wall it is in, and takes
its room from there: a door in an internal wall joins the rooms on both sides.

| Part | Settings | Sensor |
|---|---|---|
| Room (one per area) | floor area, ceiling height, volume (for a sloped ceiling), below ground, rooms beside it, rooms above it | solar gain through all its windows (W) |
| Outside wall | face, length, height | solar exposure (W/m²) |
| Roof | the rooms under it, face, pitch (`45` or `12:12`), floor area under it (or length along the eave and slope length) | solar exposure (W/m²) |
| Window | the wall or roof it is in (and, in a shared roof, its room), glass size, share let in as heat, blind (a cover) | solar gain (W), less what the blind keeps out |
| Door | the outside or internal wall it is in, its contact sensor (a binary sensor, on when open), width, height | open (follows the contact; only for a door with one) |
| Internal wall | the room on the other side, face of this room, length, height | this room minus the other (°C) |
| Heating register | thermostat, its fan or damper | heating (on while the thermostat heats) |
| Furnace | its room, input per stage (BTU/h), AFUE (%), blower curve | none |
| Air conditioner | its indoor coil's room, size (tons), sensible capacity (BTU/h) | none |
| Detached building | its rooms, such as a garage's | none |

The **furnace**, **air conditioner** and **detached building** are for
integrations that size the heating and cooling, such as Manual J. Type the
furnace's *input* from its nameplate, not its output; AFUE turns one into the
other. Its **blower curve** is the blower table's airflow against external
static pressure, such as `400 cfm = 0.30 inWC, 800 = 0.20, 1200 = 0.05`
(airflow in cfm, l/s or m3/s; static in inWC or Pa). A detached building's
rooms are sized apart from the house; its design temperatures are set in
Manual J.

A room's **rooms beside it** and **rooms above it** say which rooms it trades
heat with through its walls and ceiling. Each link counts both ways (a room
with another above it is below that one), so enter each pair once, from either
room; the form says which rooms already link to it. The first time a room is
edited, the other rooms on its floor are ticked as beside it: untick the ones
that do not touch. Any area can be chosen, such as an unheated attic or the
garage. An **open to** list is for rooms beside it with **no wall between**,
such as an open-plan kitchen: a link is open if either room lists it so.

An **internal wall** part gives a beside link its size and a temperature
difference sensor, and is where a door between two rooms goes. Its **Face**
is which side of this room the other room sits on (north, east, south or
west): set it when several neighbours share one face, such as a kitchen's east
wall that is partly outside, partly open to a landing, and partly a wall to a
bath. Leave it blank and the house drawing chooses. Its **Open** tick marks a
link with no wall (an arch, say), which keeps the sensor. The sheet below
creates these for you, and fills in the face from the rooms' footprints when
it can.

A room's **type** is a room, a **hallway** or **stairs**. A link to a hallway or
stairs is open unless the sheet says otherwise.

## Parts as a sheet

The Reconfigure form shows every part as a sheet (CSV, with a header row).
Copy it into a spreadsheet, change it, and paste the whole sheet back into
**Parts from a sheet** and submit. Each row is a part: a row with its `id`
changes that part, and a row without one adds it. The changes are then listed
for you to save, or to reject and paste a corrected sheet. Nothing is saved if
any row has a problem; the problems are listed on the form. Rooms can be given by
their name or area id, and walls by their name (give a wall a name to refer to
it from a window or door).

Give a room its footprint (`x`, `y`, `width`, `depth` and its floor's `level`,
in the house's unit) and leave its `beside`, `above` and `open` lists blank:
rooms that share an edge are then linked from the footprints, and each link gets
an internal wall part with its length. The sheet also says which outside faces
of each room have no wall part yet. Doors are added by hand.

To remove a link, put a `-` before the room in a row's `beside` or `open` list
(such as `-Den`): it comes out of both rooms. A changed room's blank lists add no
links. The internal wall part of a removed link is kept, and the sheet says so.
The [setup guide](docs/setup.md) covers the order to add parts and the sheet in
more detail.

Sheets are read with tabs or commas, so a copy from a spreadsheet works.
A part missing from the sheet is left alone. A line with only its `kind` and
`name`, and no `id`, removes that part, unless another part still uses it. A row
with an `id` and only a new `name` renames the part.

A part not square to the house can give its own compass bearing (**Facing**). A
blind is read from its cover's position (0 shut to 100 open); **Share let in
with the blind closed** is how much sun still gets through it shut. The internal
wall uses the temperature sensor chosen in each area's settings, or the area's
only temperature sensor. An area with several and none chosen has no room
sensor; the summary lists them (`temperature_choices`) so other integrations
can say so.

Each sensor's attributes give the part's geometry: compass azimuth, tilt, areas
in m², the window's wall or roof and the rooms on each side. A roof's device
sits in its first room (a device has one area); its `area_ids` attribute lists
them all.

To check the whole house at once, use **Download diagnostics** in the
integration's ⋮ menu. It lists the house settings, each part's settings (sizes
in metres) and what was built from them, any part that was skipped and why,
and every area with the parts in it, so a room you missed has none. If the
house form has measured the outline from OpenStreetMap since Home Assistant
started, it also gives the outline's walls: the way each faces and its length,
to compare with your outside walls. The file never says where the house is.

## The Thermal Lab page

House Structure adds **Thermal Lab** to Home Assistant's sidebar: a row of tabs
across the top, each showing one integration's page. Its own tab, **House**,
draws the whole house from its rooms with the heating runs (or one room on its
own, picked above the drawing) and lists the furnace, air conditioner and
detached buildings. The tab you were on is remembered, and is in the address
(`/thermal-lab#house`), so it can be bookmarked.

Above the drawing:

- **View** turns it a quarter turn at a time, to look from the south-west,
  north-west, north-east or south-east corner.
- **Floors** draws the house's floors together or pulled apart. Apart, each is
  lifted 2.5 m more than the one below, so an upper floor doesn't hide the one
  under it. A room less than 3 1/2 ft above a floor's lowest room (a split
  level's half flight) stays on that floor.
- **Show** switches the layers: the **heating runs** (on to start with), the
  **roofs** (off, as they hide the rooms), and any overlay another
  integration adds, such as Home Thermal Lab's heat flow between the rooms.

A roof is drawn as a slope rising from its eave at its pitch. A room with roofs
on opposite faces gets a gable: the two meet half way across, with the gable
ends drawn as walls (except between rooms under the same roof). Roofs on
adjacent faces (a hip) are each drawn as if the other weren't there.

The choices are remembered in your browser.

## Repairs

A wall or roof with no size, or a room with no floor area, raises a repair in
**Settings > Repairs**, but only when another integration says it needs that
number (see below). House Structure's own sensors don't use them. The repair
names the integration that needs it, links to the part's device, and goes away
once the size is given or nothing needs it any more.

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
            # the area's temperature sensors when it has several and none is
            # chosen in its settings (temperature_entity is then None)
            "temperature_choices": [],
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
            "doors": [  # a door in an internal wall is listed in both rooms
                {
                    "title": "Door to Upstairs bath",
                    "in": "internal_wall",  # or "wall" for a door to outside
                    "wall": "Wall to Upstairs bath",
                    "other_area_id": "upstairs_bath",  # None for a door to outside
                    "azimuth": None,  # the wall's, for a door to outside
                    "width_m": 0.76,
                    "height_m": 2.03,
                    "area_m2": 1.54,
                    "sensor": "binary_sensor.bath_door_contact",
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
                    "door_m2": 0.0,
                }
            ],
            "roofs": [...],  # as walls, plus "area_ids": every room under it
            "internal_walls": [
                {
                    "title": "Wall to Upstairs bath",
                    "other_area_id": "upstairs_bath",
                    "area_m2": None,
                    "door_m2": 1.54,
                    "open": False,
                    "face": "E",  # this room's face; omitted when not typed
                }
            ],
            "registers": [
                {
                    "title": "Register",
                    "climate": "climate.z3",
                    "fan": "fan.master_register",
                }
            ],
            "neighbours": [  # from both rooms' lists and internal walls
                {"area_id": "upstairs_bath", "position": "beside", "area_m2": None},
                {"area_id": "attic", "position": "above", "area_m2": None},
            ],
        },
    },
}
```

Next to `"rooms"` are the duct sections (`"ducts"`), the equipment and the
detached buildings. Powers are in W, airflow in m³/s, static pressure in Pa,
AFUE as a fraction:

```python
{
    "equipment": {
        "furnaces": [
            {
                "id": "01J...",  # the sub-entry id
                "title": "Furnace",
                "area_id": "utility",
                "input_high_w": 23446.0,
                "input_low_w": 15240.0,  # None for one stage
                "afue": 0.96,  # None if not given
                "blower": [[0.189, 74.7], [0.378, 49.8]],  # [m³/s, Pa], by airflow
            }
        ],
        "air_conditioners": [
            {
                "id": "01J...",
                "title": "Air conditioner",
                "area_id": "utility",
                "total_w": 7034.0,
                "sensible_w": None,
            }
        ],
    },
    "buildings": [{"id": "01J...", "title": "Garage", "area_ids": ["garage"]}],
}
```

Every area with a part is a room. When any of this changes, it fires the
`house_structure_updated` event. Add `"after_dependencies": ["house_structure"]`
to your manifest so it is set up first, or `"dependencies"` if your
integration can't work without it. The `version` goes up only when a key
changes meaning or goes away; new keys may be added without it.

### Adding a tab to the Thermal Lab page

Put the tab in `hass.data["house_structure_tabs"]` and fire
`house_structure_tabs_updated`; remove it, and fire the event again, when your
integration unloads. There's nothing to import, and the order you load in
doesn't matter:

```python
tabs = hass.data.setdefault("house_structure_tabs", {})
tabs["hvac_design"] = {  # the key goes in the address: a-z, 0-9 and _
    "title": "HVAC design",
    "url": "/manual_j_static/index.html?v=1a2b3c",  # a page on Home Assistant
    "order": 20,  # low first: House is 10
}
hass.bus.async_fire("house_structure_tabs_updated")
```

The tab's page is shown in a frame. Load
`/house_structure_static/tab.js` in it for Home Assistant's connection and
theme (`window.thermalLab.ask`, `subscribe`, `applyTheme`), and
`/house_structure_static/chart.umd.min.js` for Chart.js, so you don't ship
your own. The frame also passes on `window.hassConnection`, so a page that
used `window.parent.hassConnection` as a sidebar panel of its own still works.

### Drawing over the house

An overlay adds a chip to the House tab; switched on, the tab asks your
websocket command for flows in watts and draws them as arrows and labels on the
house. Register it as you would a tab, in `hass.data["house_structure_overlays"]`
with the event `house_structure_overlays_updated`:

```python
overlays = hass.data.setdefault("house_structure_overlays", {})
overlays["heat_flow"] = {
    "title": "Heat flow",
    "command": "home_thermal_lab/heat_flow",  # your websocket command
    "refresh_s": 60,  # how often it is asked again (10 at least)
}
hass.bus.async_fire("house_structure_overlays_updated")
```

The command answers with any of these (watts, positive into a room):

```python
{
    "as_of": "2026-11-04T21:00:00Z",
    "between": [
        {"from": "kitchen", "to": "office", "w": 85.0}
    ],  # across a shared wall or floor
    "outside": [
        {"room": "office", "face": "N", "w": -140.0}
    ],  # through an outside wall
    "heating": [
        {"room": "office", "w": 420.0}
    ],  # at its registers ("register": id for one)
    "solar": [{"room": "office", "w": 60.0}],
    "notes": ["Z3 has no fitted model yet."],
}
```

House Structure draws them at points it puts in the drawing: each room's
centre, the middle of each wall or floor two rooms share, each outside face
with a wall part, and each register's outlet. They follow the view and the
floors, so an overlay needn't know where anything is on the page. A value
with no such point (a room not drawn, or two rooms that don't touch) is
counted under the drawing.

### Saying what you need

To have a missing size raise a repair, say which ones you use, and fire
`house_structure_needs_updated` (remove the entry when you unload):

```python
needs = hass.data.setdefault("house_structure_needs", {})
needs["manual_j"] = {
    "title": "Manual J",  # named in the repair
    "needs": ["wall_size", "roof_size", "room_floor"],
}
hass.bus.async_fire("house_structure_needs_updated")
```

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

Chart.js is vendored into `frontend/` and pinned in `frontend/vendor.json`.
To upgrade it, change the version and URL there, run
`uv run invoke vendor` with a blank `sha256` to see the new hash, check it and
pin it, then check that every tab still draws.
