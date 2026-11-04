# Copyright (c) 2026 MinchinWeb
"""The house's heating and cooling equipment, and its detached buildings.

These parts aren't surfaces the sun shines on or rooms with walls, so they
are kept apart from ``model.Element``. They are published for other
integrations next to the rooms (see ``devices.publish_rooms``): Manual J sizes
against the furnace and air conditioner, and treats a detached building's
rooms as a separate load.

A furnace is typed in BTU/h input per stage, its AFUE in percent and its
blower curve as text; an air conditioner in tons and sensible BTU/h. They are
stored in SI (W, m³/s and Pa) with the typed text kept for the form. Standard
library only.
"""

from __future__ import annotations

import re

from .constants import AIR_CONDITIONER, BUILDING, FURNACE
from .geometry import FieldError

BTU_H_TO_W = 0.29307107
TON_TO_W = 12_000 * BTU_H_TO_W  # a ton of cooling is 12,000 BTU/h
FLOW_UNITS = {"cfm": 0.000471947, "l/s": 0.001, "m3/s": 1.0, "m³/s": 1.0}
STATIC_UNITS = {"inwc": 249.089, "pa": 1.0}  # inches of water column, pascals
_NUMBER_UNIT = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([A-Za-z][A-Za-z0-9³/]*)?\s*$")


def _number_unit(text: str, field: str) -> tuple[float, str]:
    match = _NUMBER_UNIT.match(text)
    if not match:
        raise FieldError(field, f"not a number with an optional unit: {text.strip()!r}")
    return float(match.group(1)), (match.group(2) or "").lower()


def parse_blower(text: str) -> list[tuple[float, float]]:
    """A blower curve as SI ``(airflow m³/s, static Pa)`` points, by airflow.

    Each point is ``flow = static``, separated by commas, such as
    ``400 cfm = 0.30 inWC, 800 = 0.20, 1200 = 0.05``. Units may be given on the
    first point and are carried by the rest (a point may give its own). Without
    a unit the defaults are CFM and inches of water column.
    """
    parts = [p for p in text.split(",") if p.strip()]
    if len(parts) < 2:
        raise FieldError(
            "blower_curve",
            "give at least two points, such as '400 cfm = 0.30 inWC, 800 = 0.20'",
        )
    flow_unit, static_unit = "cfm", "inwc"
    points = []
    for part in parts:
        left, sep, right = part.partition("=")
        if not sep:
            raise FieldError("blower_curve", f"not 'flow = static': {part.strip()!r}")
        flow, f_unit = _number_unit(left, "blower_curve")
        static, s_unit = _number_unit(right, "blower_curve")
        flow_unit = f_unit or flow_unit
        static_unit = s_unit or static_unit
        if flow_unit not in FLOW_UNITS:
            raise FieldError("blower_curve", f"unknown airflow unit {flow_unit!r}")
        if static_unit not in STATIC_UNITS:
            raise FieldError("blower_curve", f"unknown static unit {static_unit!r}")
        if flow <= 0 or static < 0:
            raise FieldError(
                "blower_curve", "airflow must be positive and static not negative"
            )
        points.append(
            (flow * FLOW_UNITS[flow_unit], static * STATIC_UNITS[static_unit])
        )
    points.sort()
    if len({f for f, _ in points}) != len(points):
        raise FieldError("blower_curve", "two points have the same airflow")
    return points


def _positive(form: dict, key: str) -> float | None:
    value = form.get(key)
    if value in (None, ""):
        return None
    value = float(value)
    if value <= 0:
        raise FieldError(key, "must be more than zero")
    return value


def furnace_from_form(form: dict) -> dict:
    """A furnace's stored settings from its form.

    Raises:
        FieldError: A value can't be used.
    """
    high = _positive(form, "input_high_btuh")
    if high is None:
        raise FieldError("input_high_btuh", "give the furnace's input")
    data: dict = {
        "area_id": form.get("area_id") or None,
        "input_high_w": high * BTU_H_TO_W,
    }
    low = _positive(form, "input_low_btuh")
    if low is not None:
        if low > high:
            raise FieldError("input_low_btuh", "the low stage is more than the high")
        data["input_low_w"] = low * BTU_H_TO_W
    afue = _positive(form, "afue")
    if afue is not None:
        if afue > 100:
            raise FieldError("afue", "AFUE is a percentage, such as 95")
        data["afue"] = afue / 100.0
    if (form.get("blower_curve") or "").strip():
        data["blower_curve"] = form["blower_curve"].strip()
        data["blower"] = [list(p) for p in parse_blower(data["blower_curve"])]
    return data


def furnace_to_form(data: dict) -> dict:
    """The furnace's form from its stored settings."""
    form: dict = {"area_id": data.get("area_id")}
    if data.get("input_high_w") is not None:
        form["input_high_btuh"] = round(data["input_high_w"] / BTU_H_TO_W)
    if data.get("input_low_w") is not None:
        form["input_low_btuh"] = round(data["input_low_w"] / BTU_H_TO_W)
    if data.get("afue") is not None:
        form["afue"] = round(data["afue"] * 100.0, 1)
    if data.get("blower_curve"):
        form["blower_curve"] = data["blower_curve"]
    return {k: v for k, v in form.items() if v is not None}


def air_conditioner_from_form(form: dict) -> dict:
    """An air conditioner's stored settings from its form.

    Raises:
        FieldError: A value can't be used.
    """
    tons = _positive(form, "tons")
    if tons is None:
        raise FieldError("tons", "give the air conditioner's size")
    data: dict = {"area_id": form.get("area_id") or None, "total_w": tons * TON_TO_W}
    sensible = _positive(form, "sensible_btuh")
    if sensible is not None:
        if sensible * BTU_H_TO_W > data["total_w"]:
            raise FieldError(
                "sensible_btuh", "the sensible part is more than the total"
            )
        data["sensible_w"] = sensible * BTU_H_TO_W
    return data


def air_conditioner_to_form(data: dict) -> dict:
    """The air conditioner's form from its stored settings."""
    form: dict = {"area_id": data.get("area_id")}
    if data.get("total_w") is not None:
        form["tons"] = round(data["total_w"] / TON_TO_W, 2)
    if data.get("sensible_w") is not None:
        form["sensible_btuh"] = round(data["sensible_w"] / BTU_H_TO_W)
    return {k: v for k, v in form.items() if v is not None}


def building_from_form(form: dict) -> dict:
    """A detached building's stored settings from its form.

    Raises:
        FieldError: No rooms were chosen.
    """
    areas = [a for a in form.get("area_ids") or [] if a]
    if not areas:
        raise FieldError("area_ids", "choose the building's rooms")
    return {"area_ids": areas}


def building_to_form(data: dict) -> dict:
    """The building's form from its stored settings."""
    return {"area_ids": list(data.get("area_ids") or [])}


FORMS = {
    FURNACE: (furnace_from_form, furnace_to_form),
    AIR_CONDITIONER: (air_conditioner_from_form, air_conditioner_to_form),
    BUILDING: (building_from_form, building_to_form),
}


def equipment_summary(raws: list) -> tuple[dict, list[dict]]:
    """The furnaces, air conditioners and buildings as plain data.

    Args:
        raws: The sub-entries (``model.Raw``); other kinds are ignored.

    Returns:
        ``{"furnaces": [...], "air_conditioners": [...]}`` and the buildings,
        each in the order they were added, with their sub-entry ``id`` and
        ``title``. Powers in W, airflow in m³/s, static in Pa; AFUE as a
        fraction; a blower curve as ``[[m³/s, Pa], ...]``.
    """
    equipment: dict = {"furnaces": [], "air_conditioners": []}
    buildings: list[dict] = []
    for raw in raws:
        d = raw.data
        base = {"id": raw.id, "title": raw.title}
        if raw.kind == FURNACE:
            equipment["furnaces"].append(
                {
                    **base,
                    "area_id": d.get("area_id"),
                    "input_high_w": d.get("input_high_w"),
                    "input_low_w": d.get("input_low_w"),
                    "afue": d.get("afue"),
                    "blower": [list(p) for p in d.get("blower") or []],
                }
            )
        elif raw.kind == AIR_CONDITIONER:
            equipment["air_conditioners"].append(
                {
                    **base,
                    "area_id": d.get("area_id"),
                    "total_w": d.get("total_w"),
                    "sensible_w": d.get("sensible_w"),
                }
            )
        elif raw.kind == BUILDING:
            buildings.append({**base, "area_ids": list(d.get("area_ids") or [])})
    return equipment, buildings
