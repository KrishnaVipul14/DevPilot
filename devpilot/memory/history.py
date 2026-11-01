"""High-level scan history helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devpilot.memory.database import MemoryDB


def load_history(root: Path) -> dict[str, Any]:
    return MemoryDB(root).get_history()
