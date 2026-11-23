"""App updates from GitHub Releases: check, download, verify, install."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .engine_update import _get, _version_key
from .version import GITHUB_REPO, VERSION

API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
ASSET = "ParleySetup.exe"


def check() -> dict | None:
    """Return {"version", "notes", "url", "sha_url"} if a newer release exists, else None."""
    release = json.loads(_get(API, timeout=10))
    version = str(release.get("tag_name", "")).lstrip("v")
    if not version or _version_key(version) <= _version_key(VERSION):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    return {
        "version": version,
        "notes": (release.get("body") or "").strip()[:2000],
        "url": assets.get(ASSET),
        "sha_url": assets.get(ASSET + ".sha256"),
        "page": release.get("html_url", RELEASES_PAGE),
    }


def download_and_install(info: dict) -> None:
    """Download the installer, verify it and start a silent install. The caller should then exit."""
    if sys.platform != "win32" or not info.get("url") or not info.get("sha_url"):
        raise RuntimeError("Automatic installation is only available on Windows. Download the update from GitHub.")
    expected = _get(info["sha_url"], timeout=20).decode("ascii", "ignore").split()[0].lower()
    blob = _get(info["url"], timeout=300)
    if hashlib.sha256(blob).hexdigest() != expected:
        raise RuntimeError("The downloaded update failed its integrity check. Please try again.")
    target = Path(tempfile.mkdtemp(prefix="parley-update-")) / ASSET
    target.write_bytes(blob)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(target), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"],
                     creationflags=flags, close_fds=True)
