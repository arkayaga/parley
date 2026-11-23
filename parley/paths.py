"""Per-user data locations."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    if os.environ.get("PARLEY_DATA_DIR"):  # tests and portable use
        path = Path(os.environ["PARLEY_DATA_DIR"])
        path.mkdir(parents=True, exist_ok=True)
        return path
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    path = base / "Parley"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_dir() -> Path:
    """Folder holding ui/ and assets/, both when frozen and from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent
