# Copyright (c) 2026 MinchinWeb
"""The tabs on the Thermal Lab page, as other integrations register them.

An integration adds a tab without importing House Structure:

.. code-block:: python

    tabs = hass.data.setdefault("house_structure_tabs", {})
    tabs["hvac_design"] = {
        "title": "HVAC design",
        "url": "/manual_j_static/index.html?v=1a2b3c",
        "order": 20,
    }
    hass.bus.async_fire("house_structure_tabs_updated")

and removes it, firing the event again, when it unloads. ``url`` is the page
the tab shows in a frame; it must be on Home Assistant itself (a path), since
the page asks Home Assistant for its data over the sidebar page's connection.
``order`` sorts the tabs, low first: House Structure's own House tab is 10,
Manual J's 20, Home Thermal Lab's from 30. Standard library only.
"""

from __future__ import annotations

import re

HOUSE_ORDER = 10
_KEY = re.compile(r"^[a-z0-9_]+$")


def ordered(registry: dict | None) -> list[dict]:
    """The usable tabs, sorted by ``order`` then title.

    A tab is skipped if its key isn't lower-case letters, digits and
    underscores (it goes in the page's address), it has no title, or its
    ``url`` isn't a path on Home Assistant (``/...``, not ``//host/...``).

    Returns:
        ``[{"key", "title", "url", "order"}, ...]``
    """
    out = []
    for key, tab in (registry or {}).items():
        if not isinstance(tab, dict) or not _KEY.match(str(key)):
            continue
        title = str(tab.get("title") or "").strip()
        url = str(tab.get("url") or "")
        if not title or not url.startswith("/") or url.startswith("//"):
            continue
        try:
            order = float(tab.get("order", 100))
        except TypeError, ValueError:
            order = 100.0
        out.append({"key": key, "title": title, "url": url, "order": order})
    return sorted(out, key=lambda t: (t["order"], t["title"].lower(), t["key"]))


_COMMAND = re.compile(r"^[a-z0-9_]+/[a-z0-9_/]+$")
MIN_REFRESH_S = 10.0
DEFAULT_REFRESH_S = 60.0


def ordered_overlays(registry: dict | None) -> list[dict]:
    """The usable overlays for the House tab's drawing, sorted by title.

    An integration adds one as it adds a tab, in
    ``hass.data["house_structure_overlays"]`` with the event
    ``house_structure_overlays_updated``:

    .. code-block:: python

        overlays["heat_flow"] = {
            "title": "Heat flow",
            "command": "home_thermal_lab/heat_flow",  # its websocket command
            "refresh_s": 60,
        }

    An overlay is skipped if its key isn't lower-case letters, digits and
    underscores, it has no title, or its command isn't ``domain/name``.
    ``refresh_s`` is at least ``MIN_REFRESH_S``.

    Returns:
        ``[{"key", "title", "command", "refresh_s"}, ...]``
    """
    out = []
    for key, overlay in (registry or {}).items():
        if not isinstance(overlay, dict) or not _KEY.match(str(key)):
            continue
        title = str(overlay.get("title") or "").strip()
        command = str(overlay.get("command") or "")
        if not title or not _COMMAND.match(command):
            continue
        try:
            refresh = float(overlay.get("refresh_s", DEFAULT_REFRESH_S))
        except TypeError, ValueError:
            refresh = DEFAULT_REFRESH_S
        out.append(
            {
                "key": key,
                "title": title,
                "command": command,
                "refresh_s": max(refresh, MIN_REFRESH_S),
            }
        )
    return sorted(out, key=lambda o: (o["title"].lower(), o["key"]))
