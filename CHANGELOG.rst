Changelog
=========

.. release:: unreleased

  - :feature:`-` Rooms, outside walls, roofs, windows, internal walls and heating registers, each a sub-entry of the integration and a device in a Home Assistant area. Sensors: sun on each wall and roof (W/m², from Open-Meteo every 15 minutes), solar gain through each window and each room's windows (W, following the blind's position), the temperature difference across each internal wall (from the areas' temperature sensors), and whether each register is heating. Sizes are typed in the house's unit and kept in metres. Each room's parts are published in ``hass.data["house_structure"]`` for other integrations, with a ``house_structure_updated`` event when they change. Split out of `ha-home-thermal-lab <https://github.com/minchinweb/ha-home-thermal-lab>`_.
