# Copyright (c) 2026 MinchinWeb
"""Fetch the sky's light from Open-Meteo every 15 minutes."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .constants import DOMAIN
from .sky import Sky, build_url, parse

_LOGGER = logging.getLogger(__name__)


class SkyCoordinator(DataUpdateCoordinator[list[Sky]]):
    """Yesterday's, today's and tomorrow's light at the home location."""

    def __init__(self, hass, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=15),
        )

    async def _async_update_data(self) -> list[Sky]:
        url = build_url(self.hass.config.latitude, self.hass.config.longitude)
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(30):
                response = await session.get(url)
                response.raise_for_status()
                body = await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Open-Meteo did not answer: {err}") from err
        readings = parse(body)
        if not readings:
            raise UpdateFailed("Open-Meteo sent no light readings")
        return readings
