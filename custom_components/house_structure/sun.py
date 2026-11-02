# Copyright (c) 2026 MinchinWeb
"""Where the sun is: elevation and compass azimuth, good to about a degree."""

from __future__ import annotations

from datetime import UTC, datetime
import math


def _hour_angle_and_declination(
    when: datetime, longitude: float
) -> tuple[float, float]:
    utc = when.astimezone(UTC)
    day = utc.timetuple().tm_yday
    declination = math.radians(23.44) * math.sin(2 * math.pi * (284 + day) / 365.0)
    b = 2 * math.pi * (day - 81) / 364.0
    equation_of_time = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    solar_hours = (
        utc.hour
        + utc.minute / 60.0
        + utc.second / 3600.0
        + longitude / 15.0
        + equation_of_time / 60.0
    )
    return math.radians(15.0 * (solar_hours - 12.0)), declination


def sun_position(
    when: datetime, latitude: float, longitude: float
) -> tuple[float, float]:
    """The sun's compass azimuth and elevation, in degrees.

    Args:
        when: The moment (timezone-aware).
        latitude: Degrees north.
        longitude: Degrees east.

    Returns:
        ``(azimuth, elevation)``: azimuth clockwise from north, 0 to 360 (180 is
        due south); elevation negative below the horizon.
    """
    hour_angle, declination = _hour_angle_and_declination(when, longitude)
    lat = math.radians(latitude)
    sin_elevation = math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(
        declination
    ) * math.cos(hour_angle)
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, sin_elevation))))
    south_based = math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(lat) - math.tan(declination) * math.cos(lat),
    )
    return (math.degrees(south_based) + 180.0) % 360.0, elevation
