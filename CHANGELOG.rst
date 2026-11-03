Changelog
=========

.. release:: unreleased

  - :feature:`-` Adding, changing or removing a part **no longer reloads the integration**, so the other parts' sensors stay available (no more blips of "unavailable" in their history). Changing the house's own settings still reloads it.
  - :feature:`-` A failed Open-Meteo fetch **keeps the last answer** while it still covers the time, instead of making every sensor unavailable for 15 minutes.
  - :feature:`-` **Diagnostics** download: the house and each part's settings and what was built from them, skipped parts, every area with its parts (so a room left out shows up), the sky now, and the OpenStreetMap outline as wall bearings and lengths (no position).
  - :feature:`-` **Feet and inches** as a unit: lengths are typed as ``12' 6"`` (or ``12 6``, ``150"``); floor areas and volumes in square and cubic feet.
  - :feature:`-` A **roof can cover several rooms**: it is listed in each room's summary (with ``area_ids``), its device sits in the first, and a skylight in it can name the room it lights. Roofs saved with one room keep it.
  - :feature:`-` The house form measures the **house rotation** from the building outline on OpenStreetMap and draws it, with **Redraw the map** to check another value before saving (from Home Thermal Lab).
  - :feature:`-` **Sky source** on the house: Open-Meteo (the default) or a solar radiation sensor, read every 5 minutes and split into the sun's beam and the rest of the sky (Erbs model).
  - :feature:`-` The sun's position comes from ``astral`` (as Home Assistant's ``sun.sun`` does), allowing for refraction near the horizon.
  - :feature:`-` Rooms, outside walls, roofs, windows, internal walls and heating registers, each a sub-entry of the integration and a device in a Home Assistant area. Sensors: sun on each wall and roof (W/m², from Open-Meteo every 15 minutes), solar gain through each window and each room's windows (W, following the blind's position), the temperature difference across each internal wall (from the areas' temperature sensors), and whether each register is heating. Sizes are typed in the house's unit and kept in metres. Each room's parts are published in ``hass.data["house_structure"]`` for other integrations, with a ``house_structure_updated`` event when they change. Split out of `ha-home-thermal-lab <https://github.com/minchinweb/ha-home-thermal-lab>`_.
