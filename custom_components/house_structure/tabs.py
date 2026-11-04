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
