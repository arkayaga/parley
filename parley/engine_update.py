"""Self-repair for the speech engine.

The speech service occasionally changes its handshake, which breaks older
releases of the ``edge-tts`` package. That package is pure Python, so a newer
release can be downloaded from PyPI and loaded at runtime without rebuilding
the application. A downloaded release is only kept if a live test passes.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.abc
import importlib.machinery
import io
import json
import shutil
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

from .paths import data_dir

PYPI_URL = "https://pypi.org/pypi/edge-tts/json"
PACKAGE = "edge_tts"
_finder: "_EngineFinder | None" = None


class _EngineFinder(importlib.abc.MetaPathFinder):
    """Loads edge_tts from a downloaded folder ahead of the bundled copy."""

    def __init__(self, folder: Path):
        self.folder = str(folder)

    def find_spec(self, name, path=None, target=None):
        if name == PACKAGE:
            return importlib.machinery.PathFinder.find_spec(name, [self.folder])
        if name.startswith(PACKAGE + "."):
            return importlib.machinery.PathFinder.find_spec(name, path)
        return None


def _engines_dir() -> Path:
    path = data_dir() / "engine"
    path.mkdir(exist_ok=True)
    return path


def _state_file() -> Path:
    return _engines_dir() / "active.json"


def _purge_modules() -> None:
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
        del sys.modules[name]


def _use(folder: Path | None):
    global _finder
    if _finder is not None:
        sys.meta_path.remove(_finder)
        _finder = None
    if folder is not None:
        _finder = _EngineFinder(folder)
        sys.meta_path.insert(0, _finder)
    _purge_modules()
    importlib.invalidate_caches()
    return importlib.import_module(PACKAGE)


def activate_saved() -> None:
    """Call once at start-up, before anything imports edge_tts."""
    try:
        state = json.loads(_state_file().read_text("utf-8"))
        folder = _engines_dir() / state["folder"]
        if (folder / PACKAGE / "__init__.py").exists():
            _use(folder)
            return
    except Exception:
        pass
    _use(None)


def current_version() -> str:
    module = importlib.import_module(PACKAGE)
    return getattr(module, "__version__", "unknown")


def is_custom() -> bool:
    return _finder is not None


def reset() -> str:
    _state_file().unlink(missing_ok=True)
    _use(None)
    return current_version()


def _ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _get(url: str, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Parley"})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return response.read()


def _version_key(version: str):
    return tuple(int(p) if p.isdigit() else 0 for p in version.split("."))


def latest_release() -> tuple[str, str, str]:
    """Return (version, wheel_url, sha256) of the newest edge-tts on PyPI."""
    meta = json.loads(_get(PYPI_URL))
    version = meta["info"]["version"]
    for item in meta.get("urls", []):
        if item.get("packagetype") == "bdist_wheel" and item["filename"].endswith(".whl"):
            return version, item["url"], item["digests"]["sha256"]
    raise RuntimeError("No installable package was found for the newest speech engine.")


def _install(version: str, url: str, sha256: str) -> Path:
    blob = _get(url, timeout=60)
    if hashlib.sha256(blob).hexdigest() != sha256:
        raise RuntimeError("The downloaded speech engine failed its integrity check.")
    folder = _engines_dir() / f"edge-tts-{version}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    with zipfile.ZipFile(io.BytesIO(blob)) as wheel:
        for member in wheel.namelist():
            parts = Path(member).parts
            if not parts or parts[0] != PACKAGE or ".." in parts or Path(member).is_absolute():
                continue
            target = folder / member
            target.parent.mkdir(parents=True, exist_ok=True)
            if not member.endswith("/"):
                target.write_bytes(wheel.read(member))
    if not (folder / PACKAGE / "__init__.py").exists():
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError("The downloaded speech engine is incomplete.")
    return folder


def repair(test) -> dict:
    """Try the newest engine from PyPI. ``test()`` must raise if speech fails.

    Returns {"changed": bool, "version": str}. Raises with a readable message
    if no working engine could be found.
    """
    before = current_version()
    previous = _finder.folder if _finder else None
    try:
        version, url, sha = latest_release()
    except Exception as exc:
        raise RuntimeError("Could not reach the update server. Check your internet connection.") from exc
    if _version_key(version) <= _version_key(before):
        raise RuntimeError(
            "You already have the newest speech engine. The service may be busy; "
            "try again later, or check for an app update."
        )
    folder = _install(version, url, sha)
    try:
        _use(folder)
        test()
    except Exception as exc:
        _use(Path(previous) if previous else None)
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError(
            f"The newest speech engine ({version}) did not work either. "
            "A fixed version of Parley is probably on its way; please check for app updates."
        ) from exc
    _state_file().write_text(json.dumps({"folder": folder.name, "version": version}), "utf-8")
    for old in _engines_dir().glob("edge-tts-*"):
        if old != folder:
            shutil.rmtree(old, ignore_errors=True)
    return {"changed": True, "version": version, "previous": before}
