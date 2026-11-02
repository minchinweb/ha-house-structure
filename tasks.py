# Copyright (c) 2026 MinchinWeb
"""Invoke tasks; run with ``uv run invoke --list``."""

from __future__ import annotations

try:
    from minchin.tasks import (  # noqa: F401
        check,
        format_code,
        lint,
        test,
        update,
        upgrade,
    )
except ImportError:
    print("[WARN] minchin.tasks not installed.")

try:
    from minchin.releaser import make_release  # noqa: F401
except ImportError:
    print("[WARN] minchin.releaser not installed.")
