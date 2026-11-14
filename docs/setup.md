# Setting up House Structure

House Structure describes your house once, in Home Assistant, and gives each room, wall, window, door and heating register a sensor. This page covers what to add and in what order, which fields you can skip for now, and how to add or change many parts at once with a spreadsheet.

## Before you start

1. **Make an area for each room** in **Settings → Areas & zones**. A room in House Structure is an area. Each wall, window, door and register is a device placed in its room's area.
2. **Have a rough plan.** For each room, note its width, depth, ceiling height, and which way each outside wall faces (north, east, south or west). Rough numbers are fine. Leave any size blank that you do not know.
3. **Pick your unit** on the house form (metres, feet and inches, and so on). Sizes are typed in that unit, or with their own unit after the number, such as `3.2 m`, `12' 6"` or `150 sq ft`.

## The order to add things

Add the parts from the integration's page, in this order, so that each form can offer the parts it needs.

1. **House** (the first form, when you add the integration). Set the house's rotation (measured from the building on OpenStreetMap when it can be found), the unit, and the sky source (Open-Meteo, or a solar radiation sensor). Everything else on this form can wait.
2. **Rooms.** One per area. Give each its size: a floor area is enough. The house drawing fits the rooms together from their links and outside walls, and shapes a room with no width or depth to fit, so positions are not needed for it. Give a room its position (east and north of the house's south-west corner, and its floor height) only to pin it exactly, or if you will use the sheet to work out which rooms touch.
3. **Outside walls and roofs.** Each is one face of a room, with its face and length. A roof can cover several rooms.
4. **Windows and skylights.** Each sits in a wall or roof you have already added, so add the wall first.
5. **Walls between rooms.** Each is a link between two rooms. Give the face of this room the other sits on when you care which side they share (a kitchen with two neighbours on its east wall, for example). The sheet (below) creates these for you from the rooms' footprints, so you rarely need to add them by hand.
6. **Doors.** Each sits in an outside wall or an internal wall. Add a door's contact sensor if it has one.
7. **Heating registers.** Each needs the thermostat (climate entity) that calls for its heat.
8. **Equipment and detached buildings** (furnace, air conditioner, a building's rooms), if you have them.

When something is missing, the form says so. A window that cannot find its wall, for example, tells you which wall it needs.

## Fields you can skip for now

These fields are optional. Leave them blank until the basics work. Each one improves a number, not whether the sensors exist.

- **Room:** volume (floor area times ceiling height is used), floor, below-ground depth, room type unless the room is a hallway or stairs.
- **Walls and roofs:** R-value, facing, shade below, and the roof's floor.
- **Windows:** glazing, frame, transmittance, blind and blind-closed share. The defaults are sensible.
- **Doors:** R-value and the contact sensor. A door without a sensor still counts as an opening.
- **Registers:** fan, free area, flow (CFM), duct, and upstream duct section.
- **House:** shared duct sections, plenum position, and the solar radiation sensor (unless you chose that sky source).

Sizes you do not know can be left blank. A missing size raises a repair only when a sensor needs it.

## Using the spreadsheet

The spreadsheet is the fastest way to enter many parts, and to change them. It is on the house's **Reconfigure** form, under **Parts as a sheet**.

### Export and edit

1. Open the house's **Reconfigure** form.
2. Copy the CSV block from the description. Paste it into any spreadsheet, or a text file.
3. Change the cells you need. Keep the header row.

Each row is one part. The `kind` column says what it is: `room`, `wall`, `roof`, `internal_wall`, `window`, `door` or `register`. The `id` column says which existing part a row changes. Leave `id` blank to add a new part.

### Sizes

A size can be typed in the house's unit, or with its own unit after the number: `3.2 m`, `12' 6"`, `12 6` (feet and inches), `150 sq ft`, `40 m³`. Quote marks for inches are fine in a sheet.

Use a decimal **point**, not a decimal comma: `1.5 m`, not `1,5 m`. In a comma-separated sheet the comma splits the cell, so the row has an extra cell and the import refuses it with `more cells than the header`. In a tab-separated sheet the size is refused as not a length. Either way nothing is saved.

### Names instead of ids

Rooms can be named by their area name, and parts by their name. Where a name matches more than one part, use the id.

A window or door's `host` is the wall or roof it sits in, by its name. A roof's `area_ids` and a room's lists take several rooms, separated by semicolons (`Kitchen; Hall`).

### Links between rooms

A room's `beside`, `above` and `open` lists name its neighbours:

- `beside`: rooms on the same floor with a wall between.
- `open`: rooms on the same floor with no wall between (an opening).
- `above`: rooms on the floor above that sit over this room.

A link is entered from either room, and it counts both ways.

- **To add a link:** list the other room in one of the rooms' cells.
- **To remove a link:** put a `-` before the room in either room's cell, such as `-Den`. For a `beside` or `open` link it comes out of both rooms; for `above`, from that room's list.
- **New rooms with blank lists:** the lists are worked out from the rooms' footprints (their position and size), so the sheet knows which rooms touch.
- **Changed rooms with blank lists:** a blank cell adds nothing. A link the other room still lists stays, so use `-` to remove it.

Every link gets an internal wall part, created for you. A link to a hallway or stairs, or one listed under `open`, is marked open (no wall between). An open wall keeps its temperature difference sensor.

A link you remove keeps its internal wall part, in case it has doors. The sheet reports these, so you can delete them by hand.

### Pasting it back

1. Paste the whole sheet into **Parts from a sheet**, and submit. The sheet is the only thing the form reads.
2. If every row is right, a **Check the sheet** page lists each change: the parts added, and each part changed with its old and new values, such as `beside: Kitchen → blank`. Nothing is saved yet.
3. Choose **Save these changes**, or **Reject and try again**. Rejecting saves nothing and brings the house form back with your sheet still in it, so you can correct it and submit again.
4. If any row is wrong, **nothing is saved**. The form lists each problem by row number, such as `Row 3: no room called 'Kitchen-ish'`. Fix those rows and paste the whole sheet again.

A blank cell changes nothing: a row needs only the cells it changes. Parts that are not in the sheet are left alone, so a sheet can hold just the rows you are editing.

### Removing a part

Removal is explicit. Write a line with only its `kind` and its `name`, and no `id`, and the part is removed. The confirmation page lists it. A removal is refused while another part still uses that part: a room that has walls or windows, or a wall with windows or doors in it. Remove those in the same sheet, or change them first.

To rename a part, keep its `id` and change only its `name`: a row with an `id` changes that part, and a row whose only change is its name renames it.

### Keeping a copy

Export the sheet before a large edit, so you can paste the old version back if you need to.

## When something does not work

- A sensor is unavailable: check the part has its room (area) and, for a window or door, its wall or roof.
- A room has no neighbours: its footprint may be blank. Give it a position and size, or list its neighbours.
- A repair says a size is missing: type the size on the part, or leave it blank if you do not need the sensor it feeds.
- The sheet says a row is wrong: read the message. It always names the row number.
