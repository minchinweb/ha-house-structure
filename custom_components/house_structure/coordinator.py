# Copyright (c) 2026 MinchinWeb
"""The sky's light, from the source the house chose.

* Open-Meteo: fetched every 15 minutes for the home location.
* A solar radiation sensor: read every 5 minutes and split into the sun's beam
  and the rest of the sky (see ``sky.split``).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfIrradiance,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .constants import DOMAIN, OPEN_METEO, SENSOR
from .sky import Sky, at, build_url, parse, split
from .sun import sun_position

_LOGGER = logging.getLogger(__name__)

# W/m2 in one of each unit a radiation sensor may report in
_TO_W_M2 = {
    UnitOfIrradiance.WATTS_PER_SQUARE_METER: 1.0,
    UnitOfIrradiance.BTUS_PER_HOUR_SQUARE_FOOT: 3.15459,
}


class SkyCoordinator(DataUpdateCoordinator[list[Sky]]):
    """The sky's light at the home location; the subclass names its source."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, every: timedelta
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=every,
        )

    def now(self) -> Sky | None:
        """The reading covering now, or ``None`` if there is none."""
        return at(self.data or [], dt_util.utcnow())


class OpenMeteoCoordinator(SkyCoordinator):
    """Yesterday's, today's and tomorrow's light, from Open-Meteo."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, timedelta(minutes=15))

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


class SensorCoordinator(SkyCoordinator):
    """The light now, from a solar radiation sensor on a flat surface."""

    EVERY = timedelta(minutes=5)

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(hass, entry, self.EVERY)
        self.entity_id = entity_id

    def now(self) -> Sky | None:
        """The last reading, unless it is older than two refreshes."""
        if not self.data:
            return None
        sky = self.data[-1]
        return sky if dt_util.utcnow() - sky.time <= 2 * self.EVERY else None

    async def _async_update_data(self) -> list[Sky]:
        state = self.hass.states.get(self.entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            raise UpdateFailed(f"{self.entity_id} has no reading")
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit not in _TO_W_M2:
            raise UpdateFailed(f"{self.entity_id} is in {unit}, not W/m²")
        try:
            light = float(state.state) * _TO_W_M2[unit]
        except ValueError as err:
            raise UpdateFailed(f"{self.entity_id} reads {state.state!r}") from err
        when = dt_util.utcnow()
        _, elevation = sun_position(
            when, self.hass.config.latitude, self.hass.config.longitude
        )
        direct, diffuse = split(light, elevation, when)
        return [Sky(when, direct, diffuse, span=timedelta(0))]


def sky_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> SkyCoordinator:
    """The coordinator for the house's sky source (Open-Meteo unless set)."""
    if entry.data.get("sky_source", OPEN_METEO) == SENSOR:
        return SensorCoordinator(hass, entry, entry.data["sky_sensor"])
    return OpenMeteoCoordinator(hass, entry)
