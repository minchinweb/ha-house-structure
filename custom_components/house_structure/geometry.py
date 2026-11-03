# Copyright (c) 2026 MinchinWeb
"""Shapes of the house: faces, pitches, sizes and the light on a plane.

Standard library only, so the tests run without Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

# The four faces of the house grid, as compass bearings before the rotation.
FACES = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}
FACE_NAMES = {"N": "north", "E": "east", "S": "south", "W": "west"}

# Units sizes can be typed in, as metres per unit. In feet and inches a length
# is typed as text (``12' 6"``); floor areas and volumes are in feet.
FEET_INCHES = "ft_in"
UNITS = {
    "m": 1.0,
    "cm": 0.01,
    "mm": 0.001,
    "in": 0.0254,
    "ft": 0.3048,
    FEET_INCHES: 0.3048,
}
INCH = 0.0254
FOOT = 12 * INCH

_NUMBER = r"\d+(?:\.\d+)?"
# inches may be a number, a fraction (1/2) or both (6 1/2)
_INCHES = rf"{_NUMBER}(?:\s+\d+/\d+)?|\d+/\d+"
# typed or curly quotes, primes, or words
_FEET_MARK = r"(?:'|\u2019|\u2032|ft|foot|feet)"
_INCH_MARK = r"(?:\"|\u201d|\u2033|''|in|inch|inches)"
_ONLY_INCHES = re.compile(rf"({_INCHES})\s*{_INCH_MARK}", re.IGNORECASE)
_FEET_AND_INCHES = re.compile(
    rf"({_NUMBER})\s*{_FEET_MARK}?(?:\s*-?\s*({_INCHES})\s*{_INCH_MARK}?)?",
    re.IGNORECASE,
)

# The south-east to south-west sky, compass degrees, where trees and neighbours
# block a low sun (as in the Thermal Lab's ``shade_below``).
SHADE_FROM, SHADE_TO = 120.0, 210.0


class FieldError(ValueError):
    """A form field that could not be read."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def parse_pitch(text: str | float) -> float:
    """A roof pitch in degrees, from degrees (``45``) or rise:run (``12:12``).

    ``4/12`` works too.
    """
    if isinstance(text, int | float):
        degrees = float(text)
    else:
        word = str(text).strip()
        ratio = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)", word)
        try:
            if ratio:
                rise, run = float(ratio[1]), float(ratio[2])
                if run == 0:
                    raise ValueError
                degrees = math.degrees(math.atan2(rise, run))
            else:
                degrees = float(word.rstrip("°"))
        except ValueError:
            raise FieldError("pitch", f"cannot read the pitch {text!r}") from None
    if not 0.0 <= degrees <= 90.0:
        raise FieldError("pitch", f"a pitch is 0 to 90 degrees, not {degrees:g}")
    return degrees


def _inches(text: str) -> float:
    total = 0.0
    for word in text.split():
        top, _, bottom = word.partition("/")
        total += float(top) / float(bottom) if bottom else float(top)
    return total


def parse_feet_inches(text: str | float) -> float:
    """A length in metres from feet and inches.

    ``12' 6"``, ``12'-6 1/2"``, ``12 ft 6 in``, ``12 6`` (feet, then inches),
    ``12.5'``, ``12`` (feet) and ``150"`` (inches only) all work.

    Raises:
        ValueError: The text is not a length.
    """
    if isinstance(text, int | float):
        return float(text) * FOOT
    word = str(text).strip()
    if match := _ONLY_INCHES.fullmatch(word):
        return _inches(match[1]) * INCH
    if match := _FEET_AND_INCHES.fullmatch(word):
        inches = _inches(match[2]) if match[2] else 0.0
        return float(match[1]) * FOOT + inches * INCH
    raise ValueError(f"cannot read the length {text!r}")


def format_feet_inches(metres: float) -> str:
    """A length in metres as feet and inches, to a tenth of an inch: ``12' 6.5"``."""
    inches = round(metres / INCH, 1)
    feet, inches = divmod(inches, 12)
    inches = round(inches, 1)
    if inches >= 12:  # rounding can reach a whole foot
        feet, inches = feet + 1, 0.0
    return f"{int(feet)}' {inches:g}\""


def face_azimuth(face: str, rotation: float) -> float:
    """Compass bearing a face of the house looks towards."""
    return (FACES[face] + rotation) % 360.0


def metres(value: float | None, unit: str) -> float | None:
    """A length in metres, or ``None`` when it was not given."""
    if value is None:
        return None
    return float(value) * UNITS[unit]


def rect_area(a: float | None, b: float | None, unit: str) -> float | None:
    """Area in square metres of an ``a`` by ``b`` rectangle, if both are known."""
    if a is None or b is None:
        return None
    return float(a) * float(b) * UNITS[unit] ** 2


def shaded(sun_azimuth: float, sun_elevation: float, shade_below: float) -> bool:
    """Whether trees and neighbours to the south block the sun's beam."""
    return SHADE_FROM <= sun_azimuth < SHADE_TO and sun_elevation < shade_below


@dataclass(frozen=True)
class Plane:
    """A flat surface of the house.

    Attributes:
        azimuth: Compass bearing it faces (outwards).
        tilt: Degrees from horizontal: 90 for a wall, the pitch for a roof.
        shade_below: Sun elevation below which the south sky is blocked.
    """

    azimuth: float
    tilt: float
    shade_below: float = 0.0

    def light(
        self,
        direct_normal: float,
        diffuse: float,
        sun_azimuth: float,
        sun_elevation: float,
    ) -> float:
        """Light on the plane in W/m2: the sun's beam plus the sky it sees.

        Args:
            direct_normal: Beam irradiance facing the sun, W/m2.
            diffuse: Diffuse irradiance on the flat, W/m2.
            sun_azimuth: Compass bearing of the sun.
            sun_elevation: Height of the sun, degrees.
        """
        if sun_elevation <= 0:
            return 0.0
        el, tilt = math.radians(sun_elevation), math.radians(self.tilt)
        cos_incidence = math.sin(el) * math.cos(tilt) + math.cos(el) * math.sin(
            tilt
        ) * math.cos(math.radians(sun_azimuth - self.azimuth))
        beam = 0.0
        if not shaded(sun_azimuth, sun_elevation, self.shade_below):
            beam = direct_normal * max(cos_incidence, 0.0)
        return beam + diffuse * (1 + math.cos(tilt)) / 2


def blind_open_fraction(state: str | None, position: float | None) -> float | None:
    """How open a blind is, 0 (shut) to 1 (open), from a cover's state.

    The position (0 to 100, 100 open) wins; without one, ``open`` is fully open
    and ``closed`` fully shut. ``None`` when the cover cannot be read.
    """
    if position is not None:
        try:
            return min(max(float(position) / 100.0, 0.0), 1.0)
        except TypeError, ValueError:
            pass
    if state in ("open", "opening", "closing"):
        return 1.0
    if state == "closed":
        return 0.0
    return None


def window_gain(
    light: float,
    glass_m2: float,
    transmittance: float,
    open_fraction: float = 1.0,
    closed_passes: float = 1.0,
) -> float:
    """Heat from the sun through a window, in watts.

    Args:
        light: Light on the window's plane, W/m2.
        glass_m2: Glass area.
        transmittance: Share of the light the glass lets through as heat.
        open_fraction: How open the blind is (1 with no blind).
        closed_passes: Share the closed blind still lets in.
    """
    blind = open_fraction + (1.0 - open_fraction) * closed_passes
    return light * glass_m2 * transmittance * blind
