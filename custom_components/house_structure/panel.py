# Copyright (c) 2026 MinchinWeb
"""The Thermal Lab page in Home Assistant's sidebar (needs Home Assistant).

House Structure owns the page; other integrations add tabs to it (see
``tabs.py``). The page (``frontend/frame.html``) is a tab bar and a frame that
shows the chosen tab's own page. House Structure's own tab, House
(``frontend/house.html``), draws the house.

The files in ``frontend/`` are served at ``/house_structure_static/`` with
long cache headers, and the page's address carries a hash of them so a new
version is fetched. They include:

* ``tab.js``: what a tab's page needs from the frame: Home Assistant's
  connection and theme. A tab page loads it from here.
* ``chart.umd.min.js``: Chart.js, vendored once for every tab (pinned in
  ``frontend/vendor.json``, refreshed with ``invoke vendor``), so opening the
  page fetches nothing from the internet.

Websocket commands, asked over the sidebar page's own connection:

* ``house_structure/tabs``: a subscription; sends ``{"tabs": [...]}`` now and
  whenever an integration adds or removes a tab.
* ``house_structure/overlays``: the same for the overlays other integrations
  draw over the House tab's drawing (``{"overlays": [...]}``).
* ``house_structure/house``: the rooms (with their names and floors), the
  equipment and the buildings, for the House tab.
* ``house_structure/layout``: the full layout (house settings, each part's
  settings and built attributes, areas with neighbours, the parts as a CSV
  sheet). For agents and the Home Assistant support MCP server.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import floor_registry as fr
import voluptuous as vol

from .constants import DOMAIN, OVERLAYS, OVERLAYS_EVENT, TABS, TABS_EVENT
from .diagnostics import house_layout
from .tabs import HOUSE_ORDER, ordered, ordered_overlays

STATIC_URL = "/house_structure_static"
PANEL_PATH = "thermal-lab"
FRONTEND = Path(__file__).parent / "frontend"
_HASHED = ("frame.html", "house.html", "tab.js", "chart.umd.min.js")
_STARTED = f"{DOMAIN}_panel"


def _version() -> str:
    """A short hash of the page files, to bust caches when they change."""
    digest = hashlib.sha256()
    for name in _HASHED:
        digest.update((FRONTEND / name).read_bytes())
    return digest.hexdigest()[:10]


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the files, add the commands and the sidebar page, once."""
    if hass.data.get(_STARTED) or hass.http is None:
        return
    hass.data[_STARTED] = True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND), cache_headers=True)]
    )
    websocket_api.async_register_command(hass, ws_tabs)
    websocket_api.async_register_command(hass, ws_overlays)
    websocket_api.async_register_command(hass, ws_house)
    websocket_api.async_register_command(hass, ws_layout)
    version = await hass.async_add_executor_job(_version)
    tabs = hass.data.setdefault(TABS, {})
    tabs["house"] = {
        "title": "House",
        "url": f"{STATIC_URL}/house.html?v={version}",
        "order": HOUSE_ORDER,
    }
    hass.bus.async_fire(TABS_EVENT)
    frontend.async_register_built_in_panel(
        hass,
        "iframe",
        sidebar_title="Thermal Lab",
        sidebar_icon="mdi:home-thermometer-outline",
        frontend_url_path=PANEL_PATH,
        require_admin=False,
        config={"url": f"{STATIC_URL}/frame.html?v={version}"},
    )


@callback
def _follow(hass: HomeAssistant, connection, msg: dict, event: str, make) -> None:
    """Send ``make()`` now, and again each time ``event`` fires."""

    @callback
    def send(_event=None) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], make()))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(event, send)
    connection.send_result(msg["id"])
    send()


@websocket_api.websocket_command({vol.Required("type"): "house_structure/tabs"})
@callback
def ws_tabs(hass: HomeAssistant, connection, msg: dict) -> None:
    """Send the tabs now, and again whenever they change."""
    _follow(
        hass,
        connection,
        msg,
        TABS_EVENT,
        lambda: {"tabs": ordered(hass.data.get(TABS))},
    )


@websocket_api.websocket_command({vol.Required("type"): "house_structure/overlays"})
@callback
def ws_overlays(hass: HomeAssistant, connection, msg: dict) -> None:
    """Send the overlays now, and again whenever they change."""
    _follow(
        hass,
        connection,
        msg,
        OVERLAYS_EVENT,
        lambda: {"overlays": ordered_overlays(hass.data.get(OVERLAYS))},
    )


def house_view(
    published: dict | None, names: dict[str, str], floors: dict[str, tuple]
) -> dict:
    """What the House tab shows, from the published summary.

    Args:
        published: ``hass.data["house_structure"]``.
        names: Each area's name, by area id.
        floors: Each area's floor as ``(level, name)``, where it has one.

    Returns:
        ``{"rooms": [{"area_id", "name", "floor"}], "equipment", "buildings"}``,
        the rooms by floor (lowest first), then name.
    """
    published = published or {}
    rooms = []
    for area_id in published.get("rooms") or {}:
        level, floor = floors.get(area_id, (None, None))
        rooms.append(
            {
                "area_id": area_id,
                "name": names.get(area_id, area_id),
                "floor": floor,
                "_level": level if level is not None else 0,
            }
        )
    rooms.sort(key=lambda r: (r["_level"], r["name"].lower()))
    for room in rooms:
        del room["_level"]
    equipment = published.get("equipment") or {"furnaces": [], "air_conditioners": []}
    return {
        "rooms": rooms,
        "equipment": equipment,
        "buildings": [
            {**b, "rooms": [names.get(a, a) for a in b.get("area_ids") or []]}
            for b in published.get("buildings") or []
        ],
        "names": names,
    }


@websocket_api.websocket_command({vol.Required("type"): "house_structure/house"})
@callback
def ws_house(hass: HomeAssistant, connection, msg: dict) -> None:
    """The rooms, equipment and buildings, for the House tab."""
    areas = ar.async_get(hass)
    floor_registry = fr.async_get(hass)
    names: dict[str, str] = {}
    floors: dict[str, tuple] = {}
    for area in areas.async_list_areas():
        names[area.id] = area.name
        floor = floor_registry.async_get_floor(area.floor_id) if area.floor_id else None
        if floor is not None:
            floors[area.id] = (floor.level, floor.name)
    connection.send_result(msg["id"], house_view(hass.data.get(DOMAIN), names, floors))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "house_structure/layout",
        vol.Optional("include_sheet", default=True): bool,
    }
)
@callback
def ws_layout(hass: HomeAssistant, connection, msg: dict) -> None:
    """The full house layout: settings, parts, areas and optional CSV sheet."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_result(
            msg["id"],
            {"error": "House Structure is not set up"},
        )
        return
    connection.send_result(
        msg["id"],
        house_layout(
            hass,
            entries[0],
            include_sheet=msg.get("include_sheet", True),
        ),
    )
