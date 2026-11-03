# Copyright (c) 2026 MinchinWeb
"""Shared fixtures; most come from pytest-homeassistant-custom-component."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from `custom_components/`."""
    return


@pytest.fixture(autouse=True)
def osm() -> Iterator[MagicMock]:
    """OpenStreetMap, which finds no building unless a test gives it one."""
    with patch(
        "custom_components.house_structure.config_flow.fetch_outlines",
        return_value=[],
    ) as fetch:
        yield fetch
