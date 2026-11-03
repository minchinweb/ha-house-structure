# Copyright (c) 2026 MinchinWeb
"""The sky's light: from Open-Meteo, or split from a sensor's reading.

Open-Meteo (no key needed) gives the light every 15 minutes. Its radiation is
the mean over the 15 minutes *before* the stamp, so the reading for now is the
first one stamped at or after now.

A solar radiation sensor (as on many weather stations) reads only the light on
a flat surface; ``split`` shares that between the sun's beam and the rest of
the sky. Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
import urllib.parse

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
STEP = timedelta(minutes=15)

# the sun's light above the air, W/m2, at the mean distance from the sun
SOLAR_CONSTANT = 1361.0
# below this elevation (degrees) the beam is too uncertain to split out
LOW_SUN = 2.0
# the most of the light above the air that reaches the ground as beam
MOST_DIRECT = 0.8


@dataclass(frozen=True)
class Sky:
    """Mean light over the ``span`` ending at ``time`` (UTC), in W/m2.

    Attributes:
        time: End of the span.
        direct_normal: Beam irradiance on a surface facing the sun.
        diffuse: Diffuse irradiance on a flat surface.
        span: How long the reading covers; nothing for a single reading.
    """

    time: datetime
    direct_normal: float
    diffuse: float
    span: timedelta = STEP

    @property
    def middle(self) -> datetime:
        """The middle of the span, for the sun's position."""
        return self.time - self.span / 2


def build_url(latitude: float, longitude: float) -> str:
    """The forecast URL: yesterday, today and tomorrow, in UTC."""
    query = urllib.parse.urlencode(
        {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "minutely_15": "direct_normal_irradiance,diffuse_radiation",
            "past_days": 1,
            "forecast_days": 2,
            "timezone": "GMT",
        }
    )
    return f"{FORECAST_URL}?{query}"


def parse(body: dict) -> list[Sky]:
    """Readings from the API body, oldest first, skipping missing values."""
    block = body.get("minutely_15", {})
    out = []
    for stamp, direct, diffuse in zip(
        block.get("time", []),
        block.get("direct_normal_irradiance", []),
        block.get("diffuse_radiation", []),
        strict=False,
    ):
        if direct is None or diffuse is None:
            continue
        when = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
        out.append(Sky(when, float(direct), float(diffuse)))
    return out


def at(readings: list[Sky], when: datetime) -> Sky | None:
    """The reading covering ``when``, or ``None`` if there is none."""
    for sky in readings:
        if sky.time - STEP < when <= sky.time:
            return sky
    return None


def split(
    global_horizontal: float, sun_elevation: float, when: datetime
) -> tuple[float, float]:
    """Share the light on a flat surface between the beam and the sky.

    Uses Erbs, Klein and Duffie (1982): the clearer the sky (the more of the
    light above the air that gets through), the more of it is beam.

    Args:
        global_horizontal: All the light on a flat surface, W/m2.
        sun_elevation: Height of the sun, degrees.
        when: The moment, for the earth's distance from the sun.

    Returns:
        ``(direct_normal, diffuse)`` in W/m2, as from Open-Meteo.
    """
    light = max(global_horizontal, 0.0)
    if sun_elevation < LOW_SUN:
        return 0.0, light
    day = when.timetuple().tm_yday
    above_air = SOLAR_CONSTANT * (1 + 0.033 * math.cos(2 * math.pi * day / 365.0))
    rise = math.sin(math.radians(sun_elevation))
    clearness = min(light / (above_air * rise), 1.0)
    if clearness <= 0.22:
        diffuse_share = 1.0 - 0.09 * clearness
    elif clearness <= 0.8:
        diffuse_share = (
            0.9511
            - 0.1604 * clearness
            + 4.388 * clearness**2
            - 16.638 * clearness**3
            + 12.336 * clearness**4
        )
    else:
        diffuse_share = 0.165
    diffuse = light * diffuse_share
    direct = min((light - diffuse) / rise, MOST_DIRECT * above_air)
    return direct, diffuse
