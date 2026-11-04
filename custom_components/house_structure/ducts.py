# Copyright (c) 2026 MinchinWeb
"""Duct and envelope values as typed in the forms (standard library only).

A register's duct is typed as segments, from the plenum to the register,
separated by ``;``. Each segment gives its size, its shape, its length, and
optionally ``trunk`` (for a trunk piece), ``k=`` (the sum of its fitting loss
coefficients) and ``cfm=`` (the airflow it carries, if not the register's):

    8 round 12 ft trunk cfm=400; 4 round 14 ft k=0.9
    10x6 rect 3 ft

A round size is a diameter in inches; a rectangular size is width x height in
inches. A length is in feet unless ``m`` is given. Stored segments use inches,
feet and CFM, as the duct spec in the thermal lab expects.
"""

from __future__ import annotations

import re

# An R-value in ft² °F h / BTU, to m² K / W (and back).
R_IMPERIAL_TO_SI = 0.1761101

# Whole-window U is the consumer's table; these are the choices the form offers.
GLAZINGS = ("double", "triple")
FRAMES = ("vinyl", "wood", "aluminium")

_SEGMENT = re.compile(
    r"^\s*(?P<size>\d+(?:\.\d+)?(?:\s*x\s*\d+(?:\.\d+)?)?)"
    r"\s*(?:in|\"|”)?\s*(?P<shape>round|rect)\s+"
    r"(?P<length>\d+(?:\.\d+)?)\s*(?P<unit>ft|feet|m)?\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_OPTION = re.compile(r"^(?P<key>k|cfm)\s*=\s*(?P<value>\d+(?:\.\d+)?)$", re.IGNORECASE)
_M_TO_FT = 1.0 / 0.3048


def parse_duct(text: str) -> list[dict]:
    """Segments from typed text (see the module docstring).

    Raises:
        ValueError: A segment cannot be read, with the segment in the message.
    """
    segments = []
    for part in re.split(r"[;\n]", text or ""):
        if not part.strip():
            continue
        match = _SEGMENT.match(part)
        if not match:
            raise ValueError(f"cannot read the duct segment {part.strip()!r}")
        size, shape = match.group("size"), match.group("shape").lower()
        length = float(match.group("length"))
        if match.group("unit") and match.group("unit").lower() == "m":
            length *= _M_TO_FT
        seg: dict = {"shape": shape, "length_ft": length}
        if shape == "round":
            if "x" in size.lower():
                raise ValueError(f"a round duct has one size: {part.strip()!r}")
            seg["diameter_in"] = float(size)
        else:
            if "x" not in size.lower():
                raise ValueError(
                    f"a rectangular duct needs width x height: {part.strip()!r}"
                )
            width, height = (
                float(x) for x in re.split(r"x", size, flags=re.IGNORECASE)
            )
            seg["width_in"], seg["height_in"] = width, height
        for token in match.group("rest").split():
            if token.lower() == "trunk":
                seg["trunk"] = True
                continue
            option = _OPTION.match(token)
            if not option:
                raise ValueError(f"unknown option {token!r} in {part.strip()!r}")
            key, value = option.group("key").lower(), float(option.group("value"))
            seg["fittings_k" if key == "k" else "flow_cfm"] = value
        segments.append(seg)
    return segments


def format_duct(segments: list[dict]) -> str:
    """The typed text for stored segments (the inverse of ``parse_duct``)."""
    parts = []
    for seg in segments:
        if seg["shape"] == "round":
            size = f"{seg['diameter_in']:g} round"
        else:
            size = f"{seg['width_in']:g}x{seg['height_in']:g} rect"
        text = f"{size} {seg['length_ft']:g} ft"
        if seg.get("trunk"):
            text += " trunk"
        if seg.get("fittings_k") is not None:
            text += f" k={seg['fittings_k']:g}"
        if seg.get("flow_cfm") is not None:
            text += f" cfm={seg['flow_cfm']:g}"
        parts.append(text)
    return "; ".join(parts)


_FROM = re.compile(r"^(?P<name>.+?)\s+from\s+(?P<upstream>.+)$", re.IGNORECASE)


def parse_sections(text: str) -> dict[str, dict]:
    """Shared duct sections (the plenum and trunks) from typed lines.

    One section a line, ``Name: segments``, or ``Name from Upstream: segments``
    for a section that hangs off another. The segments are as ``parse_duct``
    reads them (a section's airflow is worked out from the registers behind
    it, so its ``cfm=`` is not needed). A section with no ``from`` hangs off the
    plenum. Returns the sections by name, as ``{"upstream": name or None,
    "segments": [...]}``.

    Raises:
        ValueError: A line cannot be read, a name is used twice, an upstream
            section does not exist, or the sections loop back on themselves.
    """
    sections: dict[str, dict] = {}
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        head, colon, body = line.partition(":")
        if not colon:
            raise ValueError(f"a duct section needs a colon: {line.strip()!r}")
        found = _FROM.match(head.strip())
        name = (found.group("name") if found else head).strip()
        upstream = found.group("upstream").strip() if found else None
        if not name:
            raise ValueError(f"a duct section needs a name: {line.strip()!r}")
        if name in sections:
            raise ValueError(f"two duct sections are called {name!r}")
        segments = parse_duct(body)
        if not segments:
            raise ValueError(f"duct section {name!r} has no segments")
        sections[name] = {"upstream": upstream, "segments": segments}
    _check_tree(sections)
    return sections


def _check_tree(sections: dict[str, dict]) -> None:
    """Every upstream section exists, and following them ends at the plenum."""
    for name, section in sections.items():
        seen = [name]
        upstream = section["upstream"]
        while upstream is not None:
            if upstream not in sections:
                raise ValueError(f"no duct section called {upstream!r}")
            if upstream in seen:
                raise ValueError(f"duct sections loop back on {upstream!r}")
            seen.append(upstream)
            upstream = sections[upstream]["upstream"]


def format_sections(sections: dict[str, dict]) -> str:
    """The typed lines for sections (the inverse of ``parse_sections``)."""
    lines = []
    for name, section in sections.items():
        head = (
            name
            if section["upstream"] is None
            else f"{name} from {section['upstream']}"
        )
        lines.append(f"{head}: {format_duct(section['segments'])}")
    return "\n".join(lines)
