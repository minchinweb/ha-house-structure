# Copyright (c) 2026 MinchinWeb
"""Serve the drawing of the house outline for the house form.

The form's description shows it as an image. The drawing holds only the
building outline fetched from OpenStreetMap and the compass directions, so the
address is not in it.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .constants import OUTLINE
from .orientation import outline_svg


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
