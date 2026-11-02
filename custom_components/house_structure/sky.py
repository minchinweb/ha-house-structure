# Copyright (c) 2026 MinchinWeb
"""Sun and sky light every 15 minutes from Open-Meteo (no key needed).

Open-Meteo's 15-minute radiation is the mean over the 15 minutes *before* the
stamp, so the reading for now is the first one stamped at or after now.
Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import urllib.parse

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
STEP = timedelta(minutes=15)


@dataclass(frozen=True)
class Sky:
    """Mean light over the 15 minutes ending at ``time`` (UTC), in W/m2.

    Attributes:
        time: End of the 15 minutes.
        direct_normal: Beam irradiance on a surface facing the sun.
        diffuse: Diffuse irradiance on a flat surface.
    """

    time: datetime
    direct_normal: float
    diffuse: float

    @property
    def middle(self) -> datetime:
        """The middle of the 15 minutes, for the sun's position."""
        return self.time - STEP / 2


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
