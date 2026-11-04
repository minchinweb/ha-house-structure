# Copyright (c) 2026 MinchinWeb
"""Serve the drawings for the house forms: the outline, each room and the plan.

The forms' descriptions show them as images. The outline drawing holds only the
building outline fetched from OpenStreetMap and the compass directions, so the
address is not in it. The room and plan drawings are made from the sizes and
positions of the saved parts (see ``drawing.py``), so they are not
authenticated either, as an image in a form cannot send the login token.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .constants import DOMAIN, OUTLINE
from .devices import elements_of
from .drawing import house_svg, room_svg
from .orientation import outline_svg


def _saved_house(hass: HomeAssistant):
    """The house entry's parts and settings, or None when there is no house yet."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    entry = entries[0]
    return elements_of(entry), dict(entry.data)


class RoomDrawingView(HomeAssistantView):
    """``/api/house_structure/room.svg?area=kitchen``: one room, isometric."""

    url = "/api/house_structure/room.svg"
    name = "api:house_structure:room"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Draw the room of the area, from the saved parts."""
        saved = _saved_house(self._hass)
        area = request.query.get("area")
        if saved is None or not area:
            return web.Response(status=404)
        text = room_svg(*saved, area)
        if text is None:
            return web.Response(status=404)
        return web.Response(
            text=text,
            content_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )


class HousePlanView(HomeAssistantView):
    """``/api/house_structure/plan.svg``: the rooms, and the heating runs on them."""

    url = "/api/house_structure/plan.svg"
    name = "api:house_structure:plan"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Draw the house from its saved rooms and registers."""
        saved = _saved_house(self._hass)
        if saved is None:
            return web.Response(status=404)
        return web.Response(
            text=house_svg(*saved),
            content_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )


class OutlineMapView(HomeAssistantView):
    """``/api/house_structure/outline.svg?rotation=10.4``."""

    url = "/api/house_structure/outline.svg"
    name = "api:house_structure:outline"
    requires_auth = False  # an image in the form cannot send the login token

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Draw the outline found for the home with the requested rotation."""
        info = self._hass.data.get(OUTLINE, {})
        if not info.get("points"):
            return web.Response(status=404)
        try:
            rotation = float(request.query["rotation"])
        except KeyError, ValueError:
            rotation = info["rotation"]
        return web.Response(
            text=outline_svg(info["points"], rotation),
            content_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )
