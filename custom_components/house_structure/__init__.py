# Copyright (c) 2026 MinchinWeb
"""House Structure: the rooms, walls, roofs, windows and registers of a house.

Each part is a sub-entry of the integration and a device in a Home Assistant
area, so the house's rooms are its areas. A room's own size (floor area,
ceiling height, volume) is a part too, as is each heating register, which ties
a thermostat (and the register's fan, if it has one) to the room it heats. The
devices carry sensors: the solar exposure of each wall and roof, the solar heat through
each window (less what its blind keeps out) and through all of a room's
windows, the temperature difference across each internal wall, and whether
each register is heating. Other integrations, such as Home Thermal Lab, find a
room's parts by its area.

Set up from the web interface only (see ``config_flow.py``). Light comes from
Open-Meteo every 15 minutes for the home location, or from a solar radiation
sensor the house names (see ``coordinator.py``).

``constants.py``, ``geometry.py``, ``model.py`` and ``sky.py`` use only the
standard library, and ``sun.py`` only ``astral`` (which Home Assistant ships),
so other code can import them cheaply. That is why this file imports Home
Assistant only inside its functions.
"""

from __future__ import annotations

from .constants import (  # noqa: F401  (re-exported for other integrations)
    DOMAIN,
    DOOR,
    INTERNAL_WALL,
    NEEDS_EVENT,
    PLATFORMS,
    REGISTER,
    ROOF,
    ROOM,
    UPDATED_EVENT,
    WALL,
    WINDOW,
)


async def async_setup(hass, config) -> bool:
    """Serve the house's drawings and the Thermal Lab page in the sidebar."""
    from .map_view import HousePlanView, RoomDrawingView
    from .panel import async_register_panel

    if hass.http is not None:
        hass.http.register_view(RoomDrawingView(hass))
        hass.http.register_view(HousePlanView(hass))
    await async_register_panel(hass)
    return True


async def async_setup_entry(hass, entry) -> bool:
    """Fetch the sky, then create the devices and sensors."""
    from homeassistant.core import callback

    from .coordinator import sky_coordinator
    from .devices import (
        HouseData,
        elements_of,
        publish_rooms,
        raws_of,
        register_devices,
        sections_of,
    )
    from .issues import check

    elements = elements_of(entry)
    register_devices(hass, entry, elements)
    check(hass, entry.entry_id, elements)
    # the rooms are known before the sky, which may not answer yet
    publish_rooms(hass, elements, sections_of(entry), raws_of(entry))
    coordinator = sky_coordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = HouseData(coordinator, elements, dict(entry.data))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_updated))

    @callback
    def needs_changed(_event) -> None:
        """Another integration needs more (or less) of the house."""
        check(hass, entry.entry_id, entry.runtime_data.elements)

    entry.async_on_unload(hass.bus.async_listen(NEEDS_EVENT, needs_changed))
    return True


async def async_unload_entry(hass, entry) -> bool:
    """Remove the sensors."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass, entry) -> None:
    """Take the rooms away when the integration is deleted."""
    from .devices import publish_rooms
    from .issues import check

    check(hass, entry.entry_id, {})
    publish_rooms(hass, None)


async def _updated(hass, entry) -> None:
    """Follow a change: a part in place, the house settings by reloading.

    Reloading takes every entity away for a moment, so a part added, changed
    or removed is applied to the running entities instead (see ``entity.py``).
    """
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    from .devices import (
        elements_of,
        publish_rooms,
        raws_of,
        register_devices,
        sections_of,
    )
    from .entity import parts_signal
    from .issues import check

    data = entry.runtime_data
    if dict(entry.data) != data.house:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    data.elements = elements_of(entry)
    register_devices(hass, entry, data.elements)
    check(hass, entry.entry_id, data.elements)
    publish_rooms(hass, data.elements, sections_of(entry), raws_of(entry))
    async_dispatcher_send(hass, parts_signal(entry.entry_id))
