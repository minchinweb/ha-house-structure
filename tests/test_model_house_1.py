# Copyright (c) 2026 MinchinWeb
"""Model house 1, fitted from its typed sizes, comes out as it is built.

The main floor of a 1½-storey house: its rooms' inside sizes, outside walls
and links, as typed in a sheet (tape-measured, so a few add up an inch or
two off), its building outline, and where each room is built.

The rooms are measured inside, wall face to face, so this needs the fitter
to leave room for the walls between them.
"""

from __future__ import annotations

from custom_components.house_structure.constants import ROOM, WALL
from custom_components.house_structure.drawing import _place
from custom_components.house_structure.geometry import FEET_INCHES, FOOT, INCH
from custom_components.house_structure.model import Raw, build

# Where each room is built, inside faces, in feet from the south-west inside
# corner of the main block (x east, y north).
TRUTH = {
    "living": (0.0, 0.0, 11.91, 16.67),
    "den": (0.0, 17.04, 11.91, 21.71),
    "office": (0.0, 22.08, 11.91, 31.08),
    "hall": (12.29, 10.21, 15.21, 22.33),
    "landing": (12.29, 22.33, 24.08, 31.08),
    "bath": (15.58, 16.96, 24.08, 21.96),
    "back_hall": (15.21, 13.58, 24.08, 16.58),
    "bedroom": (14.41, 0.0, 24.08, 9.83),
    "kitchen": (24.46, 13.58, 37.71, 35.58),
}
# the building outline, outside the walls (feet)
OUTLINE = [
    (-0.5, -0.5),
    (24.58, -0.5),
    (24.58, 13.08),
    (38.21, 13.08),
    (38.21, 36.08),
    (24.58, 36.08),
    (24.58, 31.58),
    (-0.5, 31.58),
]
LIMIT = 1.5  # feet: how far a room's middle may be from where it is built


def _ft(feet: float, inches: float = 0.0) -> float:
    return feet * FOOT + inches * INCH


def _room(area: str, width, depth, **data) -> Raw:
    return Raw(
        f"room-{area}",
        ROOM,
        area,
        {
            "area_id": area,
            "width_m": width,
            "depth_m": depth,
            "height_m": _ft(8),
            **data,
        },
    )


def _wall(area: str, face: str, length: float = 0.0) -> Raw:
    data = {"area_id": area, "face": face, "height_m": _ft(8)}
    if length:
        data["length_m"] = length
    return Raw(f"wall-{area}-{face}", WALL, f"{face} wall", data)


def _parts() -> list[Raw]:
    return [
        _room("living", _ft(12), _ft(16, 8), beside=["bedroom", "hall"], open=["den"]),
        _wall("living", "W"),
        _wall("living", "S"),
        _room("den", _ft(12, 4), _ft(4, 8), open=["living", "hall", "office"]),
        _wall("den", "W"),
        _room("office", _ft(12), _ft(9), beside=["landing"], open=["den"]),
        _wall("office", "N"),
        _wall("office", "W"),
        _room(
            "hall",
            _ft(3),
            _ft(12, 4),
            room_type="hallway",
            beside=["bedroom", "living", "bath"],
            open=["den", "landing"],
        ),
        _room("landing", _ft(12), _ft(8, 6), beside=["bath", "office"]),
        _wall("landing", "N"),
        _room(
            "bath",
            _ft(8, 6),
            _ft(5),
            beside=["back_hall", "landing", "hall", "kitchen"],
        ),
        _room(
            "back_hall",
            _ft(9),
            _ft(3),
            room_type="hallway",
            beside=["bath"],
            open=["kitchen", "hall"],
        ),
        _room(
            "bedroom",
            _ft(9, 8),
            _ft(9, 10),
            wing_face="W",
            wing_width_m=_ft(2, 2),
            wing_depth_m=_ft(9, 10),
        ),
        _wall("bedroom", "S"),
        _wall("bedroom", "E"),
        _room("kitchen", _ft(13, 3), _ft(22), open=["back_hall", "landing"]),
        _wall("kitchen", "E", _ft(22)),
        _wall("kitchen", "N", _ft(13, 3)),
        _wall("kitchen", "S", _ft(13, 3)),
        _wall("kitchen", "W", _ft(4, 8)),
        # the basement stairs come up between the bedroom and the back hall
        _room(
            "stairs",
            _ft(9),
            _ft(3),
            room_type="stairs",
            stairs_to="back_hall",
            beside=["bedroom"],
            open=["back_hall"],
        ),
        # and the bedroom under the one above, its place typed (as deep as
        # that one, so that it reaches the stairs where they are built)
        _room(
            "bedroom_below",
            _ft(11),
            _ft(9, 10),
            above=["bedroom"],
            beside=["stairs"],
            x_m=_ft(13.58),
            y_m=_ft(0.5),
        ),
        _wall("bedroom_below", "S"),
        _wall("bedroom_below", "E"),
    ]


def _middle(rect) -> tuple[float, float]:
    return (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2


def _fit() -> tuple[dict[str, float], list[str]]:
    """How far (feet) each main-floor room's middle is from where it is
    built, and the notes on placing them."""
    elements, problems = build({"unit": FEET_INCHES, "rotation": 0.0}, _parts())
    assert not problems
    floors = dict.fromkeys(TRUTH, 0) | {"stairs": -1, "bedroom_below": -1}
    outline = [(x * FOOT, y * FOOT) for x, y in OUTLINE]
    boxes, notes = _place(elements, FEET_INCHES, floors, 0.0, outline)
    found = {
        b.area: (
            b.x / FOOT,
            b.y / FOOT,
            (b.x + b.width) / FOOT,
            (b.y + b.depth) / FOOT,
        )
        for b in boxes
    }
    # the house may be anywhere: line it up with the truth first
    dx = sum(_middle(TRUTH[k])[0] - _middle(found[k])[0] for k in TRUTH) / len(TRUTH)
    dy = sum(_middle(TRUTH[k])[1] - _middle(found[k])[1] for k in TRUTH) / len(TRUTH)
    off = {}
    for key, rect in TRUTH.items():
        (tx, ty), (fx, fy) = _middle(rect), _middle(found[key])
        off[key] = round(((fx + dx - tx) ** 2 + (fy + dy - ty) ** 2) ** 0.5, 1)
    return off, notes


def test_model_house_1_meets_every_link():
    _, notes = _fit()
    assert not [n for n in notes if "could not be placed" in n], notes


def test_model_house_1_comes_out_as_it_is_built():
    # before rooms had walls between them, the rooms were 19 ft out on
    # average, and the kitchen 38; with walls but only the slicing tree to
    # search with, 9 ft
    off, _ = _fit()
    assert all(v <= LIMIT for v in off.values()), off
