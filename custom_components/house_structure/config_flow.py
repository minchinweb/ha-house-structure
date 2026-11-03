# Copyright (c) 2026 MinchinWeb
"""Set up House Structure from the web interface.

The integration entry holds what is true of the whole house: how it is turned
from north, the sun elevation below which the south sky is blocked, the unit
sizes are typed in, and where the sky's light comes from (Open-Meteo, or a
solar radiation sensor). The house form measures the rotation from the
building outline on OpenStreetMap and shows a drawing to check it against (see
``orientation.py``); ticking "Redraw the map" redraws it for another value
without saving. Each part (room, wall, roof, window, internal wall,
heating register) is a sub-entry, added from the integration's page, and sits
in an area (a room). A window is placed in a wall or roof and takes its room
and its plane from it. A room part holds the room's own size, one per area.

Sizes are shown in the house's unit and stored in metres, so changing the unit
keeps every size. This module needs Home Assistant 2025.3 or later and is not
covered by the unit tests; ``geometry.py`` and ``model.py`` are.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import selector
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import voluptuous as vol

from .constants import (
    DOMAIN,
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
from .geometry import FACE_NAMES, FACES, UNITS, FieldError, face_azimuth, parse_pitch
from .map_view import OutlineMapView
from .model import BLIND_CLOSED, TRANSMITTANCE
from .orientation import choose_outline, fetch_outlines, wall_rotation

_LOGGER = logging.getLogger(__name__)

_AREA = selector.AreaSelector()
_TEXT = selector.TextSelector()
_COVER = selector.EntitySelector(selector.EntitySelectorConfig(domain="cover"))
_CLIMATE = selector.EntitySelector(selector.EntitySelectorConfig(domain="climate"))
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
    INTERNAL_WALL: ("length", "height"),
    ROOM: ("height",),
    REGISTER: (),
}


def _schema(kind: str, house: dict, hosts: list[dict]) -> vol.Schema:
    unit = house.get("unit", "m")
    length = _number(unit)
    fields: dict = {}
    if kind == WINDOW:
        fields[vol.Required("host")] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=hosts, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
    else:
        fields[vol.Required("area_id")] = _AREA
    if kind == INTERNAL_WALL:
        fields[vol.Required("other_area_id")] = _AREA
    fields[vol.Optional("name")] = _TEXT
    if kind == ROOM:
        fields[vol.Optional("floor")] = _number(f"{unit}²")
    if kind == REGISTER:
        fields[vol.Required("climate")] = _CLIMATE
        fields[vol.Optional("fan")] = _FAN
    if kind in (WALL, ROOF):
        fields[vol.Required("face", default="S")] = _faces(
            float(house.get("rotation") or 0.0)
        )
    if kind == ROOF:
        fields[vol.Required("pitch")] = _TEXT
    for size in _SIZES[kind]:
        key = vol.Required(size) if kind == WINDOW else vol.Optional(size)
        fields[key] = length
    if kind == WINDOW:
        fields[vol.Optional("transmittance", default=TRANSMITTANCE)] = _SHARE
        fields[vol.Optional("blind")] = _COVER
        fields[vol.Optional("blind_closed", default=BLIND_CLOSED)] = _SHARE
    if kind == ROOM:
        fields[vol.Optional("volume")] = _number(f"{unit}³")
        fields[vol.Optional("below_ground", default=False)] = selector.BooleanSelector()
    if kind in (WALL, ROOF):
        fields[vol.Optional("facing")] = _number("°")
        fields[vol.Optional("shade_below")] = _number("°")
    return vol.Schema(fields)


def _from_form(kind: str, form: dict, house: dict) -> dict:
    """Stored data from a form, sizes in metres."""
    per = UNITS[house.get("unit", "m")]
    data: dict = {}
    for key in ("area_id", "other_area_id", "host", "face", "blind", "climate", "fan"):
        if form.get(key):
            data[key] = form[key]
    if kind == ROOM:
        data["below_ground"] = bool(form.get("below_ground", False))
    for key in ("facing", "shade_below", "transmittance", "blind_closed"):
        if form.get(key) is not None:
            data[key] = float(form[key])
    if kind == ROOF:
        data["pitch"] = parse_pitch(form.get("pitch", ""))
    for size in _SIZES[kind]:
        if form.get(size) is not None:
            if float(form[size]) <= 0:
                raise FieldError(size, "sizes must be more than 0")
            data[f"{size}_m"] = float(form[size]) * per
    for size, power in (("floor", 2), ("volume", 3)):
        if form.get(size) is not None:
            if float(form[size]) <= 0:
                raise FieldError(size, "sizes must be more than 0")
            data[f"{size}_m{power}"] = float(form[size]) * per**power
    if kind == INTERNAL_WALL and data["area_id"] == data["other_area_id"]:
        raise FieldError("other_area_id", "the two sides are the same room")
    return data


def _to_form(kind: str, data: dict, house: dict, title: str) -> dict:
    """A form's values from stored data, sizes in the house's unit."""
    per = UNITS[house.get("unit", "m")]
    form = {k: v for k, v in data.items() if not k.endswith(("_m", "_m2", "_m3"))}
    for size, power in (("floor", 2), ("volume", 3)):
        if data.get(f"{size}_m{power}") is not None:
            form[size] = round(data[f"{size}_m{power}"] / per**power, 3)
    form["name"] = title
    for size in _SIZES[kind]:
        if data.get(f"{size}_m") is not None:
            form[size] = round(data[f"{size}_m"] / per, 3)
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
            INTERNAL_WALL: InternalWallFlow,
            REGISTER: RegisterFlow,
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
                    entry = self._get_reconfigure_entry()
                    return self.async_update_reload_and_abort(
                        entry, data={**entry.data, **data}
                    )
                return self.async_create_entry(title="House structure", data=data)
        schema = vol.Schema(
            {
                vol.Optional("rotation"): _number("°"),
                vol.Optional("preview", default=False): selector.BooleanSelector(),
                vol.Optional("shade_below"): _number("°"),
                vol.Required("unit"): _UNIT,
                vol.Required("sky_source", default=OPEN_METEO): _SKY_SOURCE,
                vol.Optional("sky_sensor"): _RADIATION,
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, current),
            description_placeholders={
                "map": await self._map_text(current.get("rotation"))
            },
            errors=errors,
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
        return await self._step("reconfigure", user_input, current)

    def _house(self) -> dict:
        return dict(self._get_entry().data)

    def _hosts(self) -> list[dict]:
        """The walls and roofs a window can be in, with their rooms."""
        areas = ar.async_get(self.hass)
        out = []
        for sub in self._get_entry().subentries.values():
            if sub.subentry_type not in (WALL, ROOF):
                continue
            area = areas.async_get_area(sub.data.get("area_id", ""))
            room = area.name if area else "no room"
            out.append({"value": sub.subentry_id, "label": f"{room}: {sub.title}"})
        return sorted(out, key=lambda o: o["label"])

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
        if self.kind == INTERNAL_WALL:
            other = areas.async_get_area(data.get("other_area_id") or "")
            return f"Wall to {other.name if other else 'another room'}"
        if self.kind == ROOM:
            return "Room"
        if self.kind == REGISTER:
            return "Register"
        return f"{facing(data)} {self.kind}".strip().capitalize()

    async def _step(
        self, step_id: str, user_input: dict[str, Any] | None, current: dict
    ) -> SubentryFlowResult:
        house = self._house()
        hosts = self._hosts() if self.kind == WINDOW else []
        if self.kind == WINDOW and not hosts:
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
            if not errors:
                title = (user_input.get("name") or "").strip() or self._default_name(
                    data
                )
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
            description_placeholders={"unit": house.get("unit", "m")},
            errors=errors,
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


class InternalWallFlow(_PartFlow):
    """A wall between two rooms."""

    kind = INTERNAL_WALL
