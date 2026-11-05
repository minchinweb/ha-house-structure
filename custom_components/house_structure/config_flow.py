# Copyright (c) 2026 MinchinWeb
"""Set up House Structure from the web interface.

The integration entry holds what is true of the whole house: how it is turned
from north, the sun elevation below which the south sky is blocked, the unit
sizes are typed in, and where the sky's light comes from (Open-Meteo, or a
solar radiation sensor). The house form measures the rotation from the
building outline on OpenStreetMap and shows a drawing to check it against (see
``orientation.py``); ticking "Redraw the map" redraws it for another value
without saving. Each part (room, wall, roof, window, door, internal wall,
heating register) is a sub-entry, added from the integration's page, and sits
in an area (a room); a roof may cover several. A window is placed in a wall
or roof and takes its plane from it, and its room too unless it is in a roof
over several rooms. A door is placed in an outside or internal wall and takes
its room (or rooms) from it, with its contact sensor. A room part holds the
room's own size, one per area.

Sizes are shown in the house's unit and stored in metres, so changing the unit
keeps every size. They are typed as text: a bare number is in the house's
unit, and a number with a unit (``3.2 m``, ``12' 6"``, ``14 sq ft``) is in
that one, whatever the house's.
This module needs Home Assistant 2025.3 or later and is not covered by the
unit tests; ``geometry.py`` and ``model.py`` are.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import selector
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import voluptuous as vol

from .constants import (
    AIR_CONDITIONER,
    BUILDING,
    DOMAIN,
    DOOR,
    FURNACE,
    INTERNAL_WALL,
    OPEN_METEO,
    OUTLINE,
    REGISTER,
    ROOF,
    ROOM,
    SENSOR,
    SKY_SOURCES,
    WALL,
    WINDOW,
)
from .ducts import (
    FRAMES,
    GLAZINGS,
    R_IMPERIAL_TO_SI,
    format_duct,
    parse_duct,
    parse_sections,
)
from .equipment import FORMS as EQUIPMENT_FORMS
from .geometry import (
    FACE_NAMES,
    FACES,
    FEET_INCHES,
    UNITS,
    FieldError,
    face_azimuth,
    format_size,
    parse_pitch,
    parse_size,
)
from .map_view import HousePlanView, OutlineMapView, RoomDrawingView
from .model import BLIND_CLOSED, TRANSMITTANCE, roof_areas
from .orientation import choose_outline, fetch_outlines, wall_rotation

_LOGGER = logging.getLogger(__name__)

_AREA = selector.AreaSelector()
_AREAS = selector.AreaSelector(selector.AreaSelectorConfig(multiple=True))
_TEXT = selector.TextSelector()
_TEXT_LINES = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
_COVER = selector.EntitySelector(selector.EntitySelectorConfig(domain="cover"))
_CLIMATE = selector.EntitySelector(selector.EntitySelectorConfig(domain="climate"))
_CONTACT = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="binary_sensor")
)
_FAN = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["fan", "switch", "cover"])
)
_UNIT = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=list(UNITS),
        mode=selector.SelectSelectorMode.DROPDOWN,
        translation_key="unit",
    )
)
_SKY_SOURCE = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=SKY_SOURCES,
        mode=selector.SelectSelectorMode.LIST,
        translation_key="sky_source",
    )
)
_RADIATION = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="irradiance")
)
_SHARE = selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=1, step=0.05, mode="box")
)


def _number(unit: str | None = None) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            mode=selector.NumberSelectorMode.BOX,
            step="any",
            unit_of_measurement=unit,
        )
    )


def _choice(options: tuple[str, ...]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options), mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _faces(rotation: float) -> selector.SelectSelector:
    """The four faces, each with the compass bearing it looks towards."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {
                    "value": face,
                    "label": f"{FACE_NAMES[face].title()} "
                    f"({face_azimuth(face, rotation):.0f}°)",
                }
                for face in FACES
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


# the sizes on each kind of form, stored with ``_m`` after them
_SIZES = {
    WALL: ("length", "height"),
    ROOF: ("length", "slope"),
    WINDOW: ("width", "height"),
    DOOR: ("width", "height"),
    INTERNAL_WALL: ("length", "height"),
    ROOM: ("width", "depth", "height", "below_grade"),
    REGISTER: (),
}
# the positions on each kind of form (they may be negative), stored with ``_m``
_POSITIONS = {
    ROOM: ("x", "y", "level"),
    REGISTER: ("at_x", "at_y", "at_z"),
}
PLENUM = ("plenum_x", "plenum_y", "plenum_z")


def _unit_label(unit: str) -> str:
    """The house's unit as the forms' descriptions name it."""
    return "feet and inches (12' 6\")" if unit == FEET_INCHES else unit


def _schema(kind: str, house: dict, hosts: list[dict]) -> vol.Schema:
    fields: dict = {}
    if kind in (WINDOW, DOOR):
        fields[vol.Required("host")] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=hosts, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
    if kind == WINDOW:
        fields[vol.Optional("area_id")] = _AREA
    elif kind == ROOF:
        fields[vol.Required("area_ids")] = _AREAS
    elif kind != DOOR:
        fields[vol.Required("area_id")] = _AREA
    if kind == INTERNAL_WALL:
        fields[vol.Required("other_area_id")] = _AREA
    fields[vol.Optional("name")] = _TEXT
    if kind == ROOM:
        fields[vol.Optional("floor")] = _TEXT
    if kind == DOOR:
        fields[vol.Optional("sensor")] = _CONTACT
    if kind == REGISTER:
        fields[vol.Required("climate")] = _CLIMATE
        fields[vol.Optional("fan")] = _FAN
        fields[vol.Optional("free_area_in2")] = _number("in²")
        fields[vol.Optional("flow_cfm")] = _number("CFM")
        fields[vol.Optional("duct")] = _TEXT
        fields[vol.Optional("upstream")] = _TEXT
    if kind == WINDOW:
        fields[vol.Optional("glazing")] = _choice(GLAZINGS)
        fields[vol.Optional("frame")] = _choice(FRAMES)
    if kind in (WALL, ROOF, DOOR):
        fields[vol.Optional("r_imperial")] = _number("ft²·°F·h/BTU")
    if kind in (WALL, ROOF):
        fields[vol.Required("face", default="S")] = _faces(
            float(house.get("rotation") or 0.0)
        )
    if kind == ROOF:
        fields[vol.Required("pitch")] = _TEXT
        fields[vol.Optional("floor")] = _TEXT
    for size in _SIZES[kind]:
        key = vol.Required(size) if kind == WINDOW else vol.Optional(size)
        fields[key] = _TEXT
    for position in _POSITIONS.get(kind, ()):
        fields[vol.Optional(position)] = _TEXT
    if kind == WINDOW:
        fields[vol.Optional("transmittance", default=TRANSMITTANCE)] = _SHARE
        fields[vol.Optional("blind")] = _COVER
        fields[vol.Optional("blind_closed", default=BLIND_CLOSED)] = _SHARE
    if kind == ROOM:
        fields[vol.Optional("volume")] = _TEXT
        fields[vol.Optional("below_ground", default=False)] = selector.BooleanSelector()
        fields[vol.Optional("beside")] = _AREAS
        fields[vol.Optional("above")] = _AREAS
    if kind in (WALL, ROOF):
        fields[vol.Optional("facing")] = _number("°")
        fields[vol.Optional("shade_below")] = _number("°")
    return vol.Schema(fields)


def _size(size: str, value: Any, unit: str, power: int = 1) -> float:
    """A size as typed, in metres (squared or cubed for ``power`` 2 or 3)."""
    try:
        metres = parse_size(value, unit, power)
    except ValueError:
        raise FieldError(size, f"cannot read the size {value!r}") from None
    if metres <= 0:
        raise FieldError(size, "sizes must be more than 0")
    return metres


def _offset(field: str, value: Any, unit: str) -> float:
    """A position in metres, from a length typed in the house's unit."""
    text = str(value).strip()
    negative = text.startswith("-")
    try:
        metres = parse_size(text.lstrip("-").strip() or "0", unit)
    except ValueError:
        raise FieldError(field, f"cannot read the position {value!r}") from None
    return -metres if negative else metres


def _signed(metres: float, unit: str) -> str:
    """A position in metres as typed, with a minus sign when it is west or south."""
    text = format_size(abs(metres), unit)
    return f"-{text}" if metres < 0 else text


def _section_names(house: dict) -> set[str]:
    """The names of the house's duct sections (none if they are not valid)."""
    try:
        return set(parse_sections(house.get("duct_sections") or ""))
    except ValueError:
        return set()


def _from_form(kind: str, form: dict, house: dict) -> dict:
    """Stored data from a form, sizes in metres."""
    unit = house.get("unit", "m")
    data: dict = {}
    if kind == ROOF:
        data["area_ids"] = list(form.get("area_ids") or [])
        if not data["area_ids"]:
            raise FieldError("area_ids", "choose the rooms the roof covers")
    for key in (
        "area_id",
        "other_area_id",
        "host",
        "face",
        "blind",
        "climate",
        "fan",
        "glazing",
        "frame",
        "sensor",
    ):
        if form.get(key):
            data[key] = form[key]
    if kind in (WALL, ROOF, DOOR) and form.get("r_imperial") not in (None, ""):
        if float(form["r_imperial"]) <= 0:
            raise FieldError("r_imperial", "an R-value must be more than 0")
        data["r_value_si"] = float(form["r_imperial"]) * R_IMPERIAL_TO_SI
    if kind == REGISTER:
        for key in ("free_area_in2", "flow_cfm"):
            if form.get(key) not in (None, ""):
                data[key] = float(form[key])
        if form.get("duct"):
            try:
                data["duct"] = parse_duct(form["duct"])
            except ValueError as err:
                raise FieldError("duct", str(err)) from None
        if form.get("upstream"):
            name = form["upstream"].strip()
            if name not in _section_names(house):
                raise FieldError("upstream", f"no duct section called {name!r}")
            data["upstream"] = name
    if kind == ROOM:
        data["below_ground"] = bool(form.get("below_ground", False))
        own = form.get("area_id")
        for key in ("beside", "above"):
            data[key] = [a for a in dict.fromkeys(form.get(key) or []) if a != own]
        if set(data["beside"]) & set(data["above"]):
            raise FieldError("above", "a room is both beside and above")
    for key in ("facing", "shade_below", "transmittance", "blind_closed"):
        if form.get(key) is not None:
            data[key] = float(form[key])
    if kind == ROOF:
        data["pitch"] = parse_pitch(form.get("pitch", ""))
    for size in _SIZES[kind]:
        if form.get(size) not in (None, ""):
            data[f"{size}_m"] = _size(size, form[size], unit)
    for position in _POSITIONS.get(kind, ()):
        if form.get(position) not in (None, ""):
            data[f"{position}_m"] = _offset(position, form[position], unit)
    for size, power in (("floor", 2), ("volume", 3)):
        if form.get(size) not in (None, ""):
            data[f"{size}_m{power}"] = _size(size, form[size], unit, power)
    if kind == INTERNAL_WALL and data["area_id"] == data["other_area_id"]:
        raise FieldError("other_area_id", "the two sides are the same room")
    return data


def _to_form(kind: str, data: dict, house: dict, title: str) -> dict:
    """A form's values from stored data, sizes in the house's unit."""
    unit = house.get("unit", "m")
    form = {
        k: v
        for k, v in data.items()
        if not k.endswith(("_m", "_m2", "_m3")) and k not in ("duct", "r_value_si")
    }
    if data.get("r_value_si") is not None:
        form["r_imperial"] = data["r_value_si"] / R_IMPERIAL_TO_SI
    if data.get("duct"):
        form["duct"] = format_duct(data["duct"])
    if kind == ROOF:
        form.pop("area_id", None)
        form["area_ids"] = roof_areas(data)
    for size, power in (("floor", 2), ("volume", 3)):
        if data.get(f"{size}_m{power}") is not None:
            form[size] = format_size(data[f"{size}_m{power}"], unit, power)
    form["name"] = title
    for size in _SIZES[kind]:
        if data.get(f"{size}_m") is None:
            continue
        form[size] = format_size(data[f"{size}_m"], unit)
    for position in _POSITIONS.get(kind, ()):
        if data.get(f"{position}_m") is not None:
            form[position] = _signed(data[f"{position}_m"], unit)
    if kind == ROOF and "pitch" in data:
        form["pitch"] = f"{data['pitch']:g}"
    return form


class HouseStructureConfigFlow(ConfigFlow, domain=DOMAIN):
    """The one entry: the house's rotation, shading, unit and sky source."""

    VERSION = 1

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """The parts that can be added, in the order of the buttons."""
        return {
            ROOM: RoomFlow,
            WALL: WallFlow,
            ROOF: RoofFlow,
            WINDOW: WindowFlow,
            DOOR: DoorFlow,
            INTERNAL_WALL: InternalWallFlow,
            REGISTER: RegisterFlow,
            FURNACE: FurnaceFlow,
            AIR_CONDITIONER: AirConditionerFlow,
            BUILDING: BuildingFlow,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the house once."""
        imperial = self.hass.config.units is US_CUSTOMARY_SYSTEM
        current: dict = {"unit": "in" if imperial else "cm"}
        measured = (await self._outline()).get("rotation")
        if measured is not None:
            current["rotation"] = measured
        return await self._house_step("user", user_input, current)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the rotation, shading, unit or sky source."""
        current = dict(self._get_reconfigure_entry().data)
        if "rotation" not in current:  # nothing saved yet: suggest the measured one
            measured = (await self._outline()).get("rotation")
            if measured is not None:
                current["rotation"] = measured
        unit = current.get("unit", "m")
        for key in PLENUM:  # saved in metres, typed in the house's unit
            if current.get(f"{key}_m") is not None:
                current[key] = _signed(current[f"{key}_m"], unit)
        if current.get("below_grade_m") is not None:
            current["below_grade"] = format_size(current["below_grade_m"], unit)
        return await self._house_step("reconfigure", user_input, current)

    async def _house_step(
        self, step_id: str, user_input: dict[str, Any] | None, current: dict
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get("preview"):
            # redraw the map for the values typed so far; nothing is saved
            current = {k: v for k, v in user_input.items() if k != "preview"}
            user_input = None
        if user_input is not None:
            try:
                data = _house(user_input)
            except FieldError as err:
                errors[err.field] = f"invalid_{err.field}"
                current = user_input
            else:
                if step_id == "reconfigure":
                    # the entry's update listener reloads it, so this must not
                    # (async_update_and_abort does this, from 2025.11)
                    entry = self._get_reconfigure_entry()
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, **data}
                    )
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_create_entry(title="House structure", data=data)
        schema = vol.Schema(
            {
                vol.Optional("rotation"): _number("°"),
                vol.Optional("preview", default=False): selector.BooleanSelector(),
                vol.Optional("shade_below"): _number("°"),
                vol.Required("unit"): _UNIT,
                vol.Required("sky_source", default=OPEN_METEO): _SKY_SOURCE,
                vol.Optional("sky_sensor"): _RADIATION,
                vol.Optional("below_grade"): _TEXT,
                vol.Optional("duct_sections"): _TEXT_LINES,
                **{vol.Optional(key): _TEXT for key in PLENUM},
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, current),
            description_placeholders={
                "map": await self._map_text(current.get("rotation")),
                "plan": self._plan_text(step_id),
            },
            errors=errors,
        )

    def _plan_text(self, step_id: str) -> str:
        """Markdown for the form: the plan of the saved house, once it is saved."""
        if step_id != "reconfigure":
            return (
                "The plan of the rooms and heating runs appears here once the "
                "house is saved."
            )
        url = f"{HousePlanView.url}?v={int(time.time())}"
        return (
            f"![House plan]({url})\n\nThe rooms at their positions and floor levels, "
            "from their sizes, with the heating runs from the plenum to each register. "
            "The runs are schematic: each is drawn straight across at the plenum's "
            "height, then up or down to its outlet. The lengths are under the plan, "
            "the run drawn beside the duct typed. Saved parts only."
        )

    async def _outline(self) -> dict:
        """The building outline at the home position, fetched once from OSM."""
        if OUTLINE in self.hass.data:
            return self.hass.data[OUTLINE]
        lat, lon = self.hass.config.latitude, self.hass.config.longitude
        try:
            outlines = await self.hass.async_add_executor_job(fetch_outlines, lat, lon)
        except OSError, ValueError, KeyError:
            _LOGGER.warning("Could not fetch the building outline from OpenStreetMap")
            return {"failed": True}  # not kept, so a later form tries again
        points = choose_outline(outlines, (lat, lon))
        info: dict = {}
        if points:
            info = {"points": points, "rotation": round(wall_rotation(points)[0], 1)}
            if self.hass.http is not None:  # kept, so the view is registered once
                self.hass.http.register_view(OutlineMapView(self.hass))
        self.hass.data[OUTLINE] = info
        return info

    async def _map_text(self, rotation: float | None) -> str:
        """Markdown for the form: the drawing, or why there is none."""
        info = await self._outline()
        if info.get("failed"):
            return (
                "Could not reach OpenStreetMap to measure the rotation. Type it if "
                "you know it, or try again later with Reconfigure."
            )
        if not info.get("points"):
            return (
                "No building was found at your home position on OpenStreetMap, "
                "so type the rotation if you know it."
            )
        shown = info["rotation"] if rotation is None else float(rotation)
        url = f"{OutlineMapView.url}?rotation={shown}&v={int(time.time())}"
        return (
            f"![House outline]({url})\n\nMeasured from the building outline on "
            f"OpenStreetMap: rotated {info['rotation']:+.1f}°. The orange cross "
            f"is the compass cross turned by {shown:+.1f}° (the dashed grey one is "
            "true north); the walls should run along it. The picture does not "
            'update as you type: tick "Redraw the map" and press Submit to see '
            "another value without saving."
        )


def _below_grade_default(house: dict) -> str:
    """The house's default below-grade depth, as the room form shows it."""
    if house.get("below_grade_m") is None:
        return "none set: the whole wall is taken as below grade"
    return format_size(house["below_grade_m"], house.get("unit", "m"))


def _house(form: dict) -> dict:
    data = {
        "unit": form.get("unit", "m"),
        "sky_source": form.get("sky_source", OPEN_METEO),
    }
    for key in ("rotation", "shade_below"):
        if form.get(key) is not None:
            data[key] = float(form[key])
    if form.get("sky_sensor"):
        data["sky_sensor"] = form["sky_sensor"]
    elif data["sky_source"] == SENSOR:
        raise FieldError("sky_sensor", "choose the solar radiation sensor")
    if form.get("duct_sections") is not None:
        try:
            parse_sections(form["duct_sections"])
        except ValueError as err:
            raise FieldError("duct_sections", str(err)) from None
        data["duct_sections"] = form["duct_sections"]
    for key in PLENUM:  # blank clears it: the merge keeps the old value otherwise
        value = form.get(key)
        data[f"{key}_m"] = (
            None if value in (None, "") else _offset(key, value, data["unit"])
        )
    value = form.get("below_grade")
    data["below_grade_m"] = (
        None if value in (None, "") else _size("below_grade", value, data["unit"])
    )
    return data


class _PartFlow(ConfigSubentryFlow):
    """Add or change one part; the subclass names its kind."""

    kind: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a part."""
        return await self._step("user", user_input, {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a part."""
        subentry = self._get_reconfigure_subentry()
        current = _to_form(
            self.kind, dict(subentry.data), self._house(), subentry.title
        )
        if self.kind == ROOM:
            area_id = subentry.data.get("area_id")
            if "beside" not in subentry.data:
                current["beside"] = self._same_floor(area_id)
            # links another room made show as ticked: unticking one removes it
            current["beside"] = sorted(
                set(current.get("beside") or []) | set(self._beside_links(area_id))
            )
        return await self._step("reconfigure", user_input, current)

    def _house(self) -> dict:
        return dict(self._get_entry().data)

    def _hosts(self) -> list[dict]:
        """The walls and roofs a window can be in, or the outside and internal
        walls a door can be in, with their rooms."""
        kinds = (WALL, INTERNAL_WALL) if self.kind == DOOR else (WALL, ROOF)
        areas = ar.async_get(self.hass)
        out = []
        for sub in self._get_entry().subentries.values():
            if sub.subentry_type not in kinds:
                continue
            names = [
                area.name
                for area_id in roof_areas(sub.data)
                if (area := areas.async_get_area(area_id))
            ]
            room = ", ".join(names) or "no room"
            out.append({"value": sub.subentry_id, "label": f"{room}: {sub.title}"})
        return sorted(out, key=lambda o: o["label"])

    def _in_host(self, window: dict) -> bool:
        """Whether a window's own room, if it names one, is one of its host's."""
        if not window.get("area_id"):
            return True
        host = self._get_entry().subentries.get(window.get("host", ""))
        return host is not None and window["area_id"] in roof_areas(host.data)

    def _rooms(self) -> list[ConfigSubentry]:
        return [
            sub
            for sub in self._get_entry().subentries.values()
            if sub.subentry_type == ROOM
        ]

    def _linked_from_others(self, area_id: str | None) -> list[str]:
        """Areas whose room (or internal wall) already links to this room."""
        if not area_id:
            return []
        out = []
        for sub in self._get_entry().subentries.values():
            d = sub.data
            if sub.subentry_type == ROOM and d.get("area_id") != area_id:
                if area_id in (d.get("beside") or []) + (d.get("above") or []):
                    out.append(d.get("area_id"))
            elif sub.subentry_type == INTERNAL_WALL:
                if d.get("area_id") == area_id:
                    out.append(d.get("other_area_id"))
                elif d.get("other_area_id") == area_id:
                    out.append(d.get("area_id"))
        return [a for a in dict.fromkeys(out) if a]

    def _beside_links(self, area_id: str | None) -> list[str]:
        """The other rooms whose own list names this room as beside."""
        if not area_id:
            return []
        return [
            sub.data["area_id"]
            for sub in self._rooms()
            if sub.data.get("area_id") not in (None, area_id)
            and area_id in (sub.data.get("beside") or [])
        ]

    def _unlink_beside(self, area_id: str, keep: list[str]) -> None:
        """Take this room out of other rooms' beside lists, except those kept.

        The form ticks every beside link, from either side, so a room left
        unticked here must come off the other room's list too.
        """
        entry = self._get_entry()
        for sub in self._rooms():
            data = sub.data
            other = data.get("area_id")
            if other in (None, area_id) or other in keep:
                continue
            beside = data.get("beside") or []
            if area_id in beside:
                self.hass.config_entries.async_update_subentry(
                    entry,
                    sub,
                    data={**data, "beside": [a for a in beside if a != area_id]},
                )

    def _same_floor(self, area_id: str | None) -> list[str]:
        """The other rooms on this room's floor, less those linked already."""
        areas = ar.async_get(self.hass)
        area = areas.async_get_area(area_id) if area_id else None
        if area is None or area.floor_id is None:
            return []
        linked = set(self._linked_from_others(area_id))
        out = []
        for sub in self._rooms():
            other = areas.async_get_area(sub.data.get("area_id") or "")
            if (
                other is not None
                and other.id != area_id
                and other.floor_id == area.floor_id
                and other.id not in linked
            ):
                out.append(other.id)
        return sorted(out)

    def _room_taken(self, area_id: str, step_id: str) -> bool:
        """Whether another room part already has this area."""
        this = (
            self._get_reconfigure_subentry().subentry_id
            if step_id == "reconfigure"
            else None
        )
        return any(
            sub.subentry_type == ROOM
            and sub.data.get("area_id") == area_id
            and sub.subentry_id != this
            for sub in self._get_entry().subentries.values()
        )

    def _default_name(self, data: dict) -> str:
        """A name for the part's device, without its room.

        Home Assistant shows a device with its area (and puts the area in its
        entity ids), so the room's name is not repeated.
        """
        areas = ar.async_get(self.hass)

        def facing(part: dict) -> str:
            if part.get("facing") is not None:
                return f"{part['facing']:.0f}°"
            return FACE_NAMES.get(part.get("face", ""), "")

        if self.kind == WINDOW:
            host = self._get_entry().subentries.get(data.get("host", ""))
            if host is None:
                return "Window"
            what = "skylight" if host.subentry_type == ROOF else "window"
            return f"{facing(host.data)} {what}".strip().capitalize()
        if self.kind == DOOR:
            host = self._get_entry().subentries.get(data.get("host", ""))
            if host is None:
                return "Door"
            if host.subentry_type == INTERNAL_WALL:
                other = areas.async_get_area(host.data.get("other_area_id") or "")
                return f"Door to {other.name if other else 'another room'}"
            return f"{facing(host.data)} door".strip().capitalize()
        if self.kind == INTERNAL_WALL:
            other = areas.async_get_area(data.get("other_area_id") or "")
            return f"Wall to {other.name if other else 'another room'}"
        if self.kind == ROOM:
            return "Room"
        if self.kind == REGISTER:
            return "Register"
        return f"{facing(data)} {self.kind}".strip().capitalize()

    def _linked_names(self, step_id: str) -> str:
        """The rooms already linked to this one, for the room form."""
        if self.kind != ROOM or step_id != "reconfigure":
            return "none"
        area_id = self._get_reconfigure_subentry().data.get("area_id")
        areas = ar.async_get(self.hass)
        names = sorted(
            area.name
            for a in self._linked_from_others(area_id)
            if (area := areas.async_get_area(a))
        )
        return ", ".join(names) or "none"

    async def _step(
        self, step_id: str, user_input: dict[str, Any] | None, current: dict
    ) -> SubentryFlowResult:
        house = self._house()
        hosts = self._hosts() if self.kind in (WINDOW, DOOR) else []
        if self.kind in (WINDOW, DOOR) and not hosts:
            return self.async_abort(reason="no_hosts")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _from_form(self.kind, user_input, house)
            except FieldError as err:
                errors[err.field] = f"invalid_{err.field}"
            else:
                if self.kind == ROOM and self._room_taken(data["area_id"], step_id):
                    errors["area_id"] = "room_exists"
                if self.kind == ROOM and step_id == "user":
                    # left empty when added, so its first edit can suggest them
                    for key in ("beside", "above"):
                        if not data[key]:
                            del data[key]
                if self.kind == WINDOW and not self._in_host(data):
                    errors["area_id"] = "invalid_area_id"
            if not errors:
                title = (user_input.get("name") or "").strip() or self._default_name(
                    data
                )
                if step_id == "reconfigure" and self.kind == ROOM:
                    self._unlink_beside(data["area_id"], data["beside"])
                if step_id == "reconfigure":
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        title=title,
                        data=data,
                    )
                return self.async_create_entry(title=title, data=data)
            current = user_input
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _schema(self.kind, house, hosts), current
            ),
            description_placeholders={
                "unit": _unit_label(house.get("unit", "m")),
                "linked": self._linked_names(step_id),
                "drawing": self._drawing_text(step_id),
                "below_grade_default": _below_grade_default(house),
            },
            errors=errors,
        )

    def _drawing_text(self, step_id: str) -> str:
        """Markdown for the room form: its drawing, once the room is saved."""
        if self.kind != ROOM:
            return ""
        if step_id != "reconfigure":
            return "The room's drawing appears here once it is saved."
        area = self._get_reconfigure_subentry().data.get("area_id") or ""
        url = f"{RoomDrawingView.url}?area={quote(area)}&v={int(time.time())}"
        return (
            f"![Room drawing]({url})\n\nThe room from its size and its parts as "
            "saved, looking from the south-west. Dashed faces have no wall part yet; "
            "the dots are the registers' outlets."
        )


class RoomFlow(_PartFlow):
    """A room's own size: floor area, ceiling height and volume."""

    kind = ROOM


class RegisterFlow(_PartFlow):
    """A heating register: the thermostat that feeds it, and its fan."""

    kind = REGISTER


class WallFlow(_PartFlow):
    """An outside wall of a room."""

    kind = WALL


class RoofFlow(_PartFlow):
    """The part of a roof over a room (its ceiling, if it follows the slope)."""

    kind = ROOF


class WindowFlow(_PartFlow):
    """A window in a wall or roof."""

    kind = WINDOW


class DoorFlow(_PartFlow):
    """A door in an outside or internal wall, and its contact sensor."""

    kind = DOOR


class InternalWallFlow(_PartFlow):
    """A wall between two rooms."""

    kind = INTERNAL_WALL


def _equipment_schema(kind: str) -> vol.Schema:
    """The form for a furnace, an air conditioner or a detached building."""
    name = {vol.Optional("name"): _TEXT}
    if kind == FURNACE:
        return vol.Schema(
            {
                **name,
                vol.Optional("area_id"): _AREA,
                vol.Required("input_high_btuh"): _number("BTU/h"),
                vol.Optional("input_low_btuh"): _number("BTU/h"),
                vol.Optional("afue"): _number("%"),
                vol.Optional("blower_curve"): _TEXT,
            }
        )
    if kind == AIR_CONDITIONER:
        return vol.Schema(
            {
                **name,
                vol.Optional("area_id"): _AREA,
                vol.Required("tons"): _number("tons"),
                vol.Optional("sensible_btuh"): _number("BTU/h"),
            }
        )
    return vol.Schema({**name, vol.Required("area_ids"): _AREAS})


_EQUIPMENT_NAMES = {
    FURNACE: "Furnace",
    AIR_CONDITIONER: "Air conditioner",
    BUILDING: "Detached building",
}


class _EquipmentFlow(ConfigSubentryFlow):
    """Add or change a furnace, air conditioner or detached building.

    These aren't surfaces or rooms, so they skip ``_PartFlow``'s sizes and
    hosts; ``equipment.py`` reads and writes their forms.
    """

    kind: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add one."""
        return await self._step("user", user_input, {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change one."""
        subentry = self._get_reconfigure_subentry()
        _, to_form = EQUIPMENT_FORMS[self.kind]
        current = {**to_form(dict(subentry.data)), "name": subentry.title}
        return await self._step("reconfigure", user_input, current)

    async def _step(
        self, step_id: str, user_input: dict[str, Any] | None, current: dict
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            from_form, _ = EQUIPMENT_FORMS[self.kind]
            try:
                data = from_form(user_input)
            except FieldError as err:
                errors[err.field] = f"invalid_{err.field}"
            else:
                title = (user_input.get("name") or "").strip() or _EQUIPMENT_NAMES[
                    self.kind
                ]
                if step_id == "reconfigure":
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        title=title,
                        data=data,
                    )
                return self.async_create_entry(title=title, data=data)
            current = user_input
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _equipment_schema(self.kind), current
            ),
            errors=errors,
        )


class FurnaceFlow(_EquipmentFlow):
    """A furnace: its input per stage, AFUE and blower curve."""

    kind = FURNACE


class AirConditionerFlow(_EquipmentFlow):
    """An air conditioner: its size in tons and its sensible capacity."""

    kind = AIR_CONDITIONER


class BuildingFlow(_EquipmentFlow):
    """A detached building, such as a garage: the rooms in it."""

    kind = BUILDING
