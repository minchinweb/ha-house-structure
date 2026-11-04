# Copyright (c) 2026 MinchinWeb
"""Tests for the duct text and the envelope conversions in the forms."""

from __future__ import annotations

import pytest

from custom_components.house_structure.ducts import (
    R_IMPERIAL_TO_SI,
    format_duct,
    format_sections,
    parse_duct,
    parse_sections,
)


def test_round_and_rect_segments():
    segments = parse_duct("8 round 12 ft trunk cfm=400; 10x6 rect 3 ft")
    assert segments[0] == {
        "shape": "round",
        "diameter_in": 8.0,
        "length_ft": 12.0,
        "trunk": True,
        "flow_cfm": 400.0,
    }
    assert segments[1] == {
        "shape": "rect",
        "width_in": 10.0,
        "height_in": 6.0,
        "length_ft": 3.0,
    }


def test_fitting_loss_and_metres():
    (seg,) = parse_duct("4 round 4 m k=0.9")
    assert seg["fittings_k"] == pytest.approx(0.9)
    assert seg["length_ft"] == pytest.approx(4 / 0.3048)


def test_inch_mark_and_newlines_separate_segments():
    segments = parse_duct('4" round 14 ft\n6 round 5 ft')
    assert [s["diameter_in"] for s in segments] == [4.0, 6.0]


def test_empty_text_gives_no_segments():
    assert parse_duct("") == []
    assert parse_duct("  ;  ") == []


@pytest.mark.parametrize(
    "text",
    [
        "4 round",  # no length
        "10 rect 3 ft",  # rectangular size not given as width x height
        "4x6 round 3 ft",  # round with two sizes
        "4 round 3 ft wibble",  # unknown option
        "fish",
    ],
)
def test_bad_segments_are_refused(text):
    with pytest.raises(ValueError):
        parse_duct(text)


def test_format_reads_back():
    text = "8 round 12 ft trunk cfm=400; 10x6 rect 3 ft; 4 round 14 ft k=0.9"
    assert parse_duct(format_duct(parse_duct(text))) == parse_duct(text)


def test_r_conversion_is_standard():
    # R-20 imperial is about 3.5 m² K/W
    assert pytest.approx(3.52, abs=0.01) == 20 * R_IMPERIAL_TO_SI


def test_sections_hang_off_each_other():
    sections = parse_sections(
        "Plenum trunk: 8 round 6 ft\nTrunk B from Plenum trunk: 6 round 8 ft k=0.4"
    )
    assert sections["Plenum trunk"]["upstream"] is None
    assert sections["Trunk B"]["upstream"] == "Plenum trunk"
    assert sections["Trunk B"]["segments"][0]["diameter_in"] == 6.0
    assert sections["Trunk B"]["segments"][0]["fittings_k"] == pytest.approx(0.4)


def test_sections_read_back():
    text = "Plenum: 8 round 6 ft\nB from Plenum: 6 round 8 ft\nC from B: 4x6 rect 3 ft"
    sections = parse_sections(text)
    assert parse_sections(format_sections(sections)) == sections


def test_empty_sections_are_nothing():
    assert parse_sections("") == {}
    assert parse_sections("\n  \n") == {}


@pytest.mark.parametrize(
    "text",
    [
        "Trunk 8 round 6 ft",  # no colon
        "Trunk: ",  # no segments
        ": 8 round 6 ft",  # no name
        "A from B: 4 round 3 ft",  # B does not exist
        "A: 4 round 3 ft\nA: 4 round 2 ft",  # the name twice
        "A from B: 4 round 3 ft\nB from A: 4 round 3 ft",  # loops
        "A from A: 4 round 3 ft",  # hangs off itself
    ],
)
def test_bad_sections_are_refused(text):
    with pytest.raises(ValueError):
        parse_sections(text)
