# Copyright (c) 2026 MinchinWeb
"""Parts from a spreadsheet, for the Reconfigure form: check a pasted sheet
against the house, write it, or export the house's parts as a sheet.

A row with an ``id`` changes that part; a row without one adds a part. Each
row is read the way its form reads it (``config_flow._from_form``), and nothing
is written unless every row is. A room's ``beside``, ``above`` and ``open`` lists
say its neighbours: a neighbour listed ``open`` (or a hallway or stairs on
either side, when the lists are left blank) is open, with no wall between. A
``-`` before a room in those lists takes that link out of both rooms. Every link
without an internal wall part gets one, and one that is open gets ``open``; no
part is ever removed. Doors are added by hand.

This module imports ``config_flow``, which imports it only inside a function,
so the two never import each other at load time.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers import area_registry as ar
from homeassistant.util.ulid import ulid_now

from .config_flow import _from_form, _to_form, default_title
from .constants import (
    DOOR,
    INTERNAL_WALL,
    OPEN_ROOM_TYPES,
    REGISTER,
    ROOF,
    ROOM,
    WALL,
    WINDOW,
)
from .geometry import FACE_NAMES, FieldError, format_size
from .sheet import (
    COLUMNS,
    Footprint,
    dump,
    links,
    outside_faces,
    parse,
    shared_face,
    shared_length,
)

# The parts a sheet holds, in the order they are written: a host comes before the
# parts in it. Equipment has its own forms and is not in a sheet.
SHEET_KINDS = (ROOM, WALL, ROOF, INTERNAL_WALL, WINDOW, DOOR, REGISTER)
# The kinds of part a window or door can be in.
HOSTS = {WINDOW: (WALL, ROOF), DOOR: (WALL, INTERNAL_WALL)}
# The fields a row must have, as its form requires them.
REQUIRED = {
    ROOM: ("area_id",),
    WALL: ("area_id", "face"),
    ROOF: ("area_ids", "face", "pitch"),
    WINDOW: ("host", "width", "height"),
    DOOR: ("host",),
    INTERNAL_WALL: ("area_id", "other_area_id"),
    REGISTER: ("area_id", "climate"),
}
# Columns whose cells are lists of rooms (separated by semicolons), per kind.
ROOM_LISTS = {ROOM: ("beside", "above", "open"), ROOF: ("area_ids",)}
# The lists that link rooms: a link is entered by either room.
LINK_LISTS = ("beside", "above", "open")


@dataclass
class SheetPlan:
    """What a sheet would do: the problems (nothing else is used if there are
    any), the writes, the changes read from it and the notes for the user."""

    problems: list[str] = field(default_factory=list)
    writes: list[dict[str, Any]] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(1 for item in self.writes if item["sub"] is None)

    @property
    def removed(self) -> int:
        return sum(1 for item in self.writes if item.get("remove"))

    @property
    def changed(self) -> int:
        return len(self.writes) - self.added - self.removed


def _yes(text: str) -> bool:
    word = text.strip().lower()
    if word in ("yes", "y", "true", "1"):
        return True
    if word in ("no", "n", "false", "0", ""):
        return False
    raise ValueError(f"{text!r} is not yes or no")


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(";") if part.strip()]


def _add(names: dict[str, list[str]], name: str, sub_id: str) -> None:
    ids = names.setdefault(name.casefold(), [])
    if sub_id not in ids:
        ids.append(sub_id)


def _footprint(area_id: str, data: dict) -> Footprint | None:
    """A room's footprint, if its position and size are all given."""
    values = [data.get(key) for key in ("x_m", "y_m", "width_m", "depth_m")]
    if any(value is None for value in values):
        return None
    return Footprint(area_id, *values, level=data.get("level_m") or 0.0)


def _blank(value: Any) -> bool:
    """Whether a stored value says nothing: no value, an empty text or list."""
    return value in (None, "", [])


def _meaningful(data: dict) -> dict:
    """The data without its blank values, so a missing list and an empty one agree."""
    return {key: value for key, value in data.items() if not _blank(value)}


def _refers(target_kind: str, target: ConfigSubentry, kind: str, data: dict) -> bool:
    """Whether a part of ``kind`` with ``data`` uses ``target``, which therefore
    cannot be removed while that part stays."""
    if target_kind == ROOM:
        area = target.data.get("area_id")
        return (
            kind != ROOM
            and area is not None
            and (
                area in (data.get("area_id"), data.get("other_area_id"))
                or area in (data.get("area_ids") or [])
            )
        )
    if target_kind in (WALL, ROOF, INTERNAL_WALL):
        return kind in (WINDOW, DOOR) and data.get("host") == target.subentry_id
    return False


def plan_sheet(hass, entry: ConfigEntry, text: str) -> SheetPlan:
    """Check a sheet against the house and, if every row is right, write it.

    Returns:
        ``(problems, added, changed, notes)``. The problems are one line per row
        that could not be read, and then nothing is written. ``notes`` are the
        room faces that are outside but have no wall part yet, for the user to
        add.
    """
    problems: list[str] = []
    try:
        rows = parse(text)
    except ValueError as err:
        return SheetPlan(problems=[str(err)])
    house = dict(entry.data)
    unit = house.get("unit", "m")
    areas = ar.async_get(hass)
    area_ids = {area.id for area in areas.async_list_areas()}
    area_names: dict[str, list[str]] = {}
    for area in areas.async_list_areas():
        _add(area_names, area.name, area.id)
    existing = dict(entry.subentries)
    kinds = {sub_id: sub.subentry_type for sub_id, sub in existing.items()}
    part_names: dict[str, list[str]] = {}
    for sub in existing.values():
        _add(part_names, sub.title, sub.subentry_id)

    def area_of(value: str) -> str:
        if value in area_ids:
            return value
        found = set(area_names.get(value.casefold(), []))
        if len(found) == 1:
            return found.pop()
        if found:
            raise ValueError(f"more than one room is called {value!r}; use its id")
        raise ValueError(f"no room called {value!r}")

    def name_of(area_id: str | None) -> str:
        area = areas.async_get_area(area_id or "")
        return area.name if area else (area_id or "")

    def part_of(value: str) -> str:
        if value in existing:
            return value
        found = set(part_names.get(value.casefold(), []))
        if len(found) == 1:
            return found.pop()
        if found:
            raise ValueError(f"more than one part is called {value!r}; use its id")
        raise ValueError(f"no part called {value!r}")

    def removal_target(kind: str, cells: dict[str, str]) -> ConfigSubentry:
        """The part a removal line names: by its name (a room's area name, or its
        title)."""
        wanted = cells["name"].casefold()
        found = [
            sub
            for sub in existing.values()
            if sub.subentry_type == kind
            and (
                sub.title.casefold() == wanted
                or (
                    kind == ROOM
                    and name_of(sub.data.get("area_id")).casefold() == wanted
                )
            )
        ]
        if len(found) == 1:
            return found[0]
        if found:
            raise ValueError(
                f"more than one {kind} is called {cells['name']!r}; use its id"
            )
        raise ValueError(f"no {kind} called {cells['name']!r}")

    # Pass 1: each row's kind and the part it changes, or the id it will get. A
    # line with only its kind and a name, and no id, removes that part; a row with
    # an id changes it, so one with only a new name renames it.
    read = []
    removals = []
    for number, cells in rows:
        kind = cells.get("kind", "").strip().lower()
        if kind not in SHEET_KINDS:
            problems.append(
                f"Row {number}: kind {cells.get('kind', '')!r} is not one of "
                f"{', '.join(SHEET_KINDS)}"
            )
            continue
        try:
            if (
                not any(
                    cells.get(column)
                    for column in COLUMNS
                    if column not in ("kind", "id", "name")
                )
                and cells.get("name")
                and not cells.get("id")
            ):
                removals.append((number, kind, removal_target(kind, cells)))
                continue
            sub = None
            if cells.get("id"):
                sub = existing.get(cells["id"])
                if sub is None or sub.subentry_type != kind:
                    raise ValueError(f"no {kind} part has the id {cells['id']!r}")
                sub_id = sub.subentry_id
            else:
                sub_id = ulid_now()
        except ValueError as err:
            problems.append(f"Row {number}: {err}")
            continue
        kinds[sub_id] = kind
        if cells.get("name"):
            _add(part_names, cells["name"], sub_id)
        read.append((number, kind, sub_id, sub, cells))
    removing = {sub.subentry_id for _, _, sub in removals}
    updating = {sub_id for _, _, sub_id, sub, _ in read if sub is not None} | removing

    # Pass 2: each row as the form stores it. A changed part starts from its
    # current values, so a row changes only the cells it fills in. A list cell
    # adds the rooms it names, and a ``-`` before a room takes that room out.
    taken = {
        sub.data.get("area_id"): sub.subentry_id
        for sub in existing.values()
        if sub.subentry_type == ROOM and sub.subentry_id not in updating
    }
    plans: list[dict[str, Any]] = []
    for number, kind, sub_id, sub, cells in read:
        try:
            base = (
                _to_form(kind, dict(sub.data), house, sub.title)
                if sub is not None
                else {}
            )
            row = {
                column: value
                for column, value in cells.items()
                if column not in ("id", "kind", "name") and value != ""
            }
            given = {key for key in LINK_LISTS if key in row} if kind == ROOM else set()
            for key in ("area_id", "other_area_id"):
                if key in row:
                    row[key] = area_of(row[key])
            gone: list[tuple[str, str]] = []
            for key in ROOM_LISTS.get(kind, ()):
                if key in row:
                    added: list[str] = []
                    removed: list[str] = []
                    for part in _split(row[key]):
                        if part.startswith("-"):
                            area = area_of(part[1:].strip())
                            removed.append(area)
                            if kind == ROOM and key in LINK_LISTS:
                                gone.append((key, area))
                        else:
                            added.append(area_of(part))
                    row[key] = (added, removed)
            if kind == ROOM and "below_ground" in row:
                row["below_ground"] = _yes(row["below_ground"])
            if kind == INTERNAL_WALL and "open" in row:
                row["open"] = _yes(row["open"])
            if "host" in row:
                row["host"] = part_of(row["host"])
                wanted = HOSTS.get(kind, ())
                if wanted and kinds.get(row["host"]) not in wanted:
                    raise ValueError(f"the host must be a {' or '.join(wanted)}")
            form = dict(base)
            for key, value in row.items():
                if key in ROOM_LISTS.get(kind, ()):
                    added, removed = value
                    current = [a for a in base.get(key) or [] if a not in removed]
                    form[key] = current + [a for a in added if a not in current]
                else:
                    form[key] = value
            missing = [key for key in REQUIRED.get(kind, ()) if not form.get(key)]
            if missing:
                raise ValueError(f"needs {', '.join(missing)}")
            data = _from_form(kind, form, house)
            if kind == ROOM:
                if data["area_id"] in taken:
                    raise ValueError(
                        f"{name_of(data['area_id'])} already has a room part"
                    )
                taken[data["area_id"]] = sub_id
            plans.append(
                {
                    "number": number,
                    "kind": kind,
                    "sub_id": sub_id,
                    "sub": sub,
                    "name": cells.get("name") or (sub.title if sub else ""),
                    "data": data,
                    "given": given,
                    "gone": gone,
                }
            )
        except FieldError as err:
            field = err.field
            problems.append(
                f"Row {number}, {field}: {err}" if field else f"Row {number}: {err}"
            )
        except ValueError as err:
            problems.append(f"Row {number}: {err}")

    # A removed part must not be used by a part that stays: a room by its walls,
    # windows and registers; a wall or roof by its windows and doors.
    if removals and not problems:
        states = [
            (sub.subentry_id, sub.subentry_type, sub.data, sub.title)
            for sub in existing.values()
            if sub.subentry_id not in updating
        ] + [
            (plan["sub_id"], plan["kind"], plan["data"], plan["name"] or plan["kind"])
            for plan in plans
        ]
        for number, kind, sub in removals:
            users = [
                title
                for sid, skind, sdata, title in states
                if sid not in removing and _refers(kind, sub, skind, sdata)
            ]
            if users:
                label = name_of(sub.data.get("area_id")) if kind == ROOM else sub.title
                problems.append(
                    f"Row {number}: {label} is used by {', '.join(users)}; "
                    "remove those in the sheet too"
                )
    if problems:
        return SheetPlan(problems=problems)

    # Pass 3: the rooms' links, from their footprints where a room's lists are
    # left blank, and the internal wall each link needs.
    room_data = {
        sub.data.get("area_id"): sub.data
        for sub in existing.values()
        if sub.subentry_type == ROOM and sub.subentry_id not in updating
    }
    for plan in plans:
        if plan["kind"] == ROOM:
            room_data[plan["data"]["area_id"]] = plan["data"]
    room_types = {
        area: data.get("room_type", "room") for area, data in room_data.items()
    }
    footprints = {
        area: fp
        for area, data in room_data.items()
        if (fp := _footprint(area, data)) is not None
    }
    beside_all, above_all = links(list(footprints.values()))
    for plan in plans:
        # a new room with no lists takes them from its footprint; a changed room's
        # blank lists mean no neighbours, so clearing a cell clears the links
        if plan["kind"] != ROOM or plan["given"] or plan["sub"] is not None:
            continue
        area = plan["data"]["area_id"]
        if area not in footprints:
            continue
        neighbours = beside_all.get(area, [])
        opened = [
            other
            for other in neighbours
            if room_types.get(area) in OPEN_ROOM_TYPES
            or room_types.get(other) in OPEN_ROOM_TYPES
        ]
        plan["data"]["beside"] = [other for other in neighbours if other not in opened]
        plan["data"]["open"] = opened
        plan["data"]["above"] = above_all.get(area, [])
        room_data[area] = plan["data"]

    # A ``-room`` in a row's lists takes that link out of both rooms: a beside or
    # open link from each room's lists, an above link from the room's own list.
    # A room that is not in the sheet is written with its lists changed.
    room_subs = {
        sub.data.get("area_id"): sub
        for sub in existing.values()
        if sub.subentry_type == ROOM
    }
    in_sheet = {plan["data"]["area_id"] for plan in plans if plan["kind"] == ROOM}
    unlinked: set[frozenset] = set()
    rewritten: dict[str, ConfigSubentry] = {}

    def drop(area: str, key: str, other: str) -> None:
        data = room_data.get(area)
        if data is None or other not in (data.get(key) or []):
            return
        values = [item for item in data[key] if item != other]
        if key != "above":
            unlinked.add(frozenset((area, other)))
        if area in in_sheet:
            data[key] = values
        else:
            room_data[area] = {**data, key: values}
            rewritten[area] = room_subs[area]

    for plan in plans:
        if plan["kind"] != ROOM:
            continue
        area = plan["data"]["area_id"]
        for key, other in plan["gone"]:
            if key == "above":
                drop(area, "above", other)
            else:
                for lst in ("beside", "open"):
                    drop(area, lst, other)
                    drop(other, lst, area)

    for _, kind, sub in removals:
        if kind == ROOM:
            area = sub.data.get("area_id")
            for other in list(room_data):
                for key in ("beside", "open", "above"):
                    drop(other, key, area)

    open_pairs: dict[frozenset, bool] = {}
    for area, data in room_data.items():
        for other in data.get("beside") or []:
            open_pairs.setdefault(frozenset((area, other)), False)
        for other in data.get("open") or []:
            open_pairs[frozenset((area, other))] = True
    walls: dict[frozenset, dict[str, Any]] = {}
    for sub in existing.values():
        if sub.subentry_type == INTERNAL_WALL and sub.subentry_id not in updating:
            pair = frozenset((sub.data.get("area_id"), sub.data.get("other_area_id")))
            walls[pair] = {"sub": sub, "data": sub.data}
    for plan in plans:
        if plan["kind"] == INTERNAL_WALL:
            pair = frozenset((plan["data"]["area_id"], plan["data"]["other_area_id"]))
            walls[pair] = {"sub": plan["sub"], "data": plan["data"], "row": plan}

    # A row that changes nothing is not written.
    writes: list[dict[str, Any]] = [
        plan
        for plan in plans
        if plan["sub"] is None
        or _meaningful(plan["data"]) != _meaningful(plan["sub"].data)
        or plan["name"] != plan["sub"].title
    ]
    for _number, kind, sub in removals:
        writes.append(
            {
                "kind": kind,
                "sub_id": sub.subentry_id,
                "sub": sub,
                "name": "",
                "data": {},
                "remove": True,
            }
        )
    for area, sub in rewritten.items():
        writes.append(
            {
                "kind": ROOM,
                "sub_id": sub.subentry_id,
                "sub": sub,
                "name": sub.title,
                "data": room_data[area],
            }
        )
    auto_added = 0
    for pair, is_open in sorted(open_pairs.items(), key=lambda item: sorted(item[0])):
        if len(pair) != 2:
            continue
        first, second = sorted(pair)
        if pair in walls:
            wall = walls[pair]
            if "row" not in wall and bool(wall["data"].get("open")) != is_open:
                # the room lists decide an existing link's kind
                writes.append(
                    {
                        "kind": INTERNAL_WALL,
                        "sub_id": wall["sub"].subentry_id,
                        "sub": wall["sub"],
                        "name": wall["sub"].title,
                        "data": {**wall["sub"].data, "open": is_open},
                    }
                )
            continue
        length = None
        face = None
        if first in footprints and second in footprints:
            length = shared_length(footprints[first], footprints[second])
            face = shared_face(footprints[first], footprints[second])
        heights = [
            room_data[area].get("height_m")
            for area in (first, second)
            if room_data.get(area) is not None
        ]
        heights = [h for h in heights if h is not None]
        data = {
            "area_id": first,
            "other_area_id": second,
            "open": is_open,
            "length_m": length or None,
            "height_m": min(heights) if len(heights) == 2 else None,
        }
        if face:
            data["face"] = face
        writes.append(
            {
                "kind": INTERNAL_WALL,
                "sub_id": ulid_now(),
                "sub": None,
                "name": "",
                "data": data,
            }
        )
        auto_added += 1

    # Faces of the rooms that are outside, with no wall part yet.
    walled = {
        (item["data"].get("area_id"), item["data"].get("face"))
        for item in writes
        if item["kind"] == WALL and not item.get("remove")
    }
    walled |= {
        (sub.data.get("area_id"), sub.data.get("face"))
        for sub in existing.values()
        if sub.subentry_type == WALL and sub.subentry_id not in updating
    }
    notes = []
    all_footprints = list(footprints.values())
    for plan in plans:
        if plan["kind"] != ROOM or plan["data"]["area_id"] not in footprints:
            continue
        area = plan["data"]["area_id"]
        for face, length in outside_faces(footprints[area], all_footprints).items():
            if (area, face) not in walled:
                notes.append(
                    f"{name_of(area)} {FACE_NAMES[face]} wall, "
                    f"{format_size(length, unit)}"
                )

    for pair in sorted(unlinked, key=sorted):
        if pair in walls and pair not in open_pairs and len(pair) == 2:
            first, second = sorted(pair)
            notes.append(
                f"{name_of(first)} and {name_of(second)} are no longer linked; "
                "their internal wall part is kept, so delete it by hand if it is "
                "not needed"
            )
    if auto_added:
        notes.insert(0, f"{auto_added} internal wall part(s) created for the links")
    ordered = sorted(writes, key=lambda w: SHEET_KINDS.index(w["kind"]))

    def shown(key: str, value: Any) -> str:
        if value in (None, "", []):
            return "blank"
        if isinstance(value, bool):
            return "yes" if value else "no"
        if key in ("area_id", "other_area_id"):
            return name_of(value)
        if isinstance(value, list):
            return "; ".join(name_of(item) for item in value)
        if key == "host":
            sub = entry.subentries.get(value)
            return sub.title if sub is not None else str(value)
        if key.endswith("_m") and isinstance(value, (int, float)):
            return format_size(value, unit)
        return str(value)

    changes = []
    for item in ordered:
        kind, sub, data = item["kind"], item["sub"], item["data"]
        if item.get("remove"):
            label = name_of(sub.data.get("area_id")) if kind == ROOM else sub.title
            changes.append(f"Remove a {kind.replace('_', ' ')}: {label}")
            continue
        if sub is None:
            if kind == INTERNAL_WALL:
                first = name_of(data["area_id"])
                second = name_of(data["other_area_id"])
                label = f"between {first} and {second}"
            elif kind == ROOM:
                label = name_of(data["area_id"])
            else:
                label = item["name"] or default_title(hass, entry, kind, data)
            changes.append(f"Add a {kind.replace('_', ' ')}: {label}")
            continue
        before = dict(sub.data, name=sub.title)
        after = dict(data, name=item["name"] or sub.title)
        lines = []
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key), after.get(key)
            if old != new and not (_blank(old) and _blank(new)):
                label = key.removesuffix("_m").replace("_", " ")
                lines.append(f"{label}: {shown(key, old)} → {shown(key, new)}")
        if lines:
            title = name_of(data["area_id"]) if kind == ROOM else sub.title
            changes.append(f"Change {title}: " + "; ".join(lines))
    return SheetPlan(problems=[], writes=ordered, changes=changes, notes=notes)


def apply_plan(hass, entry: ConfigEntry, plan: SheetPlan) -> None:
    """Write a checked plan: add, change and remove the parts it lists."""
    for item in plan.writes:
        if item.get("remove"):
            hass.config_entries.async_remove_subentry(entry, item["sub_id"])
            continue
        kind, sub = item["kind"], item["sub"]
        title = item["name"] or default_title(hass, entry, kind, item["data"])
        if sub is None:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=item["data"],
                    subentry_id=item["sub_id"],
                    subentry_type=kind,
                    title=title,
                    unique_id=None,
                ),
            )
        else:
            hass.config_entries.async_update_subentry(
                entry, sub, title=title, data=item["data"]
            )


def export_sheet(hass, entry: ConfigEntry) -> str:
    """The house's parts as a sheet: one row per part, with its ``id``."""
    house = dict(entry.data)
    hosts = Counter(
        sub.title
        for sub in entry.subentries.values()
        if sub.subentry_type in (WALL, ROOF, INTERNAL_WALL)
    )
    areas = ar.async_get(hass)

    def area_name(area_id: str) -> str:
        area = areas.async_get_area(area_id)
        return area.name if area else area_id

    def cell(key: str, value: Any) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, list):
            return "; ".join(area_name(item) for item in value)
        if key in ("area_id", "other_area_id"):
            return area_name(value)
        if key == "host":
            sub = entry.subentries.get(value)
            if sub is not None and hosts[sub.title] == 1:
                return sub.title
            return value
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    rows = []
    for kind in SHEET_KINDS:
        subs = sorted(
            (s for s in entry.subentries.values() if s.subentry_type == kind),
            key=lambda s: s.title.casefold(),
        )
        for sub in subs:
            form = _to_form(kind, dict(sub.data), house, sub.title)
            row = {"id": sub.subentry_id, "kind": kind}
            for key, value in form.items():
                if (
                    key in COLUMNS
                    and key not in ("id", "kind")
                    and value not in (None, "")
                ):
                    row[key] = cell(key, value)
            rows.append(row)
    return dump(rows)
