"""App updates from GitHub Releases: check, download, verify, install.

Windows: runs the new ParleySetup.exe silently; it closes and reopens Parley.
macOS:   downloads Parley-macOS.zip, swaps the .app bundle in place once this
         process has exited, and reopens it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from .engine_update import _get, _version_key
from .version import GITHUB_REPO, VERSION

API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
if sys.platform == "win32":
    ASSET = "ParleySetup.exe"
elif sys.platform == "darwin":
    ASSET = "Parley-macOS-Intel.zip" if platform.machine() == "x86_64" else "Parley-macOS.zip"
else:
    ASSET = None


def check() -> dict | None:
    """Return {"version", "notes", "url", "sha_url", "page"} if a newer release exists, else None."""
    release = json.loads(_get(API, timeout=10))
    version = str(release.get("tag_name", "")).lstrip("v")
    if not version or _version_key(version) <= _version_key(VERSION):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    return {
        "version": version,
        "notes": (release.get("body") or "").strip()[:2000],
        "url": assets.get(ASSET) if ASSET else None,
        "sha_url": assets.get(f"{ASSET}.sha256") if ASSET else None,
        "page": release.get("html_url", RELEASES_PAGE),
    }


def can_self_install(info: dict) -> bool:
    return bool(getattr(sys, "frozen", False) and info.get("url") and info.get("sha_url"))


def _download(info: dict) -> Path:
    expected = _get(info["sha_url"], timeout=20).decode("ascii", "ignore").split()[0].lower()
    blob = _get(info["url"], timeout=600)
    if hashlib.sha256(blob).hexdigest() != expected:
        raise RuntimeError("The downloaded update failed its integrity check. Please try again.")
    target = Path(tempfile.mkdtemp(prefix="parley-update-")) / ASSET
    target.write_bytes(blob)
    return target


def download_and_install(info: dict) -> None:
    """Download, verify and start installing. The caller must exit right after."""
    if not can_self_install(info):
        raise RuntimeError("This copy of Parley cannot update itself. Download the update from GitHub.")
    package = _download(info)
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(package), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"],
                         creationflags=flags, close_fds=True)
    elif sys.platform == "darwin":
        _install_mac(package)
    else:
        raise RuntimeError("Automatic updates are not supported on this system.")


def _install_mac(package: Path) -> None:
    app = Path(sys.executable).resolve().parents[2]  # .../Parley.app/Contents/MacOS/Parley
    if app.suffix != ".app":
        raise RuntimeError("Could not find the Parley app to update.")
    unpacked = package.parent / "new"
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(package), str(unpacked)], check=True)
    new_app = next(unpacked.glob("*.app"), None)
    if new_app is None:
        raise RuntimeError("The downloaded update is incomplete.")
    if not os.access(app.parent, os.W_OK):
        raise RuntimeError(f"Parley cannot replace itself in {app.parent}. Download the update from GitHub.")
    q = shlex.quote
    script = package.parent / "install.sh"
    script.write_text(f"""#!/bin/sh
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done
APP={q(str(app))}; NEW={q(str(new_app))}
rm -rf "$APP.old"
if mv "$APP" "$APP.old" && mv "$NEW" "$APP"; then
  rm -rf "$APP.old"
else
  [ -d "$APP" ] || mv "$APP.old" "$APP"
fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
open "$APP"
""")
    subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
