"""Build helpers, run from the repository root before PyInstaller.

    python packaging/build_support.py   # writes THIRD_PARTY_NOTICES.txt and build/version_info.txt
"""
from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from parley.version import VERSION  # noqa: E402

RUNTIME = ["edge-tts", "aiohttp", "aiohappyeyeballs", "aiosignal", "attrs", "frozenlist", "multidict",
           "propcache", "yarl", "idna", "certifi", "tabulate", "typing_extensions", "pywebview", "bottle",
           "proxy_tools", "pythonnet", "clr_loader", "cffi", "pycparser", "winrt-runtime"]


def license_text(dist: metadata.Distribution) -> str:
    texts = []
    for f in dist.files or []:
        name = f.name.lower()
        if re.match(r"(licen[cs]e|copying|notice|authors)", name) or "licenses/" in str(f).lower():
            try:
                texts.append(f.read_text().strip())
            except (OSError, UnicodeDecodeError):
                pass
    if not texts:
        texts.append(f"License: {dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'see project page'}")
    return "\n\n".join(dict.fromkeys(texts))


def notices() -> None:
    parts = [
        "Parley is built on the following open-source software. Their licenses are reproduced below.\n",
        "=" * 72 + "\nPython\n" + "=" * 72 + "\nPython Software Foundation License. https://docs.python.org/3/license.html\n",
        "=" * 72 + "\nInter typeface\n" + "=" * 72 + "\n" + (ROOT / "ui" / "fonts" / "OFL.txt").read_text("utf-8"),
    ]
    seen = set()
    for name in RUNTIME:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        if dist.metadata["Name"].lower() in seen:
            continue
        seen.add(dist.metadata["Name"].lower())
        header = f"{dist.metadata['Name']} {dist.version}  ({dist.metadata.get('Home-page') or ''})".rstrip(" ()")
        parts.append("=" * 72 + f"\n{header}\n" + "=" * 72 + "\n" + license_text(dist) + "\n")
    winrt = sorted({d.metadata["Name"] for d in metadata.distributions() if d.metadata["Name"].startswith("winrt-Windows")})
    if winrt:
        parts.append("Also included (MIT, same license as winrt-runtime): " + ", ".join(winrt) + "\n")
    (ROOT / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(parts), "utf-8")


def version_info() -> None:
    nums = [int(x) for x in VERSION.split(".")] + [0]
    t = tuple(nums[:4])
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build" / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Parley'),
      StringStruct('FileDescription', 'Parley - text and dialogue to speech'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'Parley'),
      StringStruct('OriginalFilename', 'Parley.exe'),
      StringStruct('ProductName', 'Parley'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", "utf-8")


if __name__ == "__main__":
    notices()
    version_info()
    print(f"Prepared build files for Parley {VERSION}")
