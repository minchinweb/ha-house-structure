# Copyright (c) 2026 MinchinWeb
"""Where the sun is: elevation and compass azimuth, from ``astral``.

``astral`` is what Home Assistant's own ``sun.sun`` uses, and Home Assistant
ships it, so nothing extra is installed. It is asked directly rather than read
from ``sun.sun`` because the sun is wanted at a chosen moment (the middle of a
reading's 15 minutes), not only now.
"""

from __future__ import annotations

from datetime import datetime

from astral import Observer
from astral.sun import azimuth, elevation


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
        due south); elevation negative below the horizon, allowing for the air
        bending the light near the horizon.
    """
    observer = Observer(latitude=latitude, longitude=longitude)
    return azimuth(observer, when), elevation(observer, when)
