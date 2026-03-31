"""Single source of truth for the application version."""
from __future__ import annotations

import os
import tomllib


def get_version() -> str:
    """Read the version from pyproject.toml at the repo root."""
    pyproject = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except Exception:
        return "unknown"


VERSION: str = get_version()
