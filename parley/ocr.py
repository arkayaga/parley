"""Read text from an image with the text recognition built into the OS.

Windows 10/11 uses Windows.Media.Ocr, macOS uses Apple's Vision framework.
Images never leave the computer.
"""
from __future__ import annotations

import re
import sys

from .script import looks_like_dialogue

_PREFIX = re.compile(r"^([A-Za-z][A-Za-z .’'\-]{0,35})\s*[:：]\s*(.*)$")
MAX_BYTES = 30 * 1024 * 1024


def _backend():
    if sys.platform == "win32":
        from . import ocr_win as backend
    elif sys.platform == "darwin":
        from . import ocr_mac as backend
    else:
        return None
    return backend


def available() -> bool:
    try:
        backend = _backend()
        return bool(backend and backend.available())
    except Exception:
        return False


def clean_line(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[•▪●]\s*", "", text)  # bullets
    text = re.sub(r"([.!?])(?=(?:[A-Z][a-z]|I\b))", r"\1 ", text)  # missing space after a sentence
    match = _PREFIX.match(text)
    if match:
        text = f"{match[1].strip()}: {match[2].strip()}".rstrip()
    return text


def merge_rows(boxes: list[tuple[float, float, float, str]]) -> list[str]:
    """Join text pieces that sit on the same visual line.

    ``boxes`` holds (left, top, height, text) with ``top`` growing downwards.
    """
    rows: list[dict] = []
    for left, top, height, text in sorted(boxes, key=lambda b: (b[1] + b[2] / 2, b[0])):
        center = top + height / 2
        if rows and abs(center - rows[-1]["center"]) <= 0.45 * min(height, rows[-1]["height"]):
            rows[-1]["items"].append((left, text))
        else:
            rows.append({"center": center, "height": height, "items": [(left, text)]})
    return [" ".join(t for _, t in sorted(r["items"])) for r in rows]


def read_image(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("Images can be up to 30 MB.")
    backend = _backend()
    if backend is None or not backend.available():
        raise ValueError("Reading text from images is not available on this computer.")
    try:
        lines = backend.recognize(data)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The image could not be read. Try a PNG or JPG file.") from exc
    text = "\n".join(clean_line(l) for l in lines if l.strip())
    if not text.strip():
        raise ValueError("No readable text was found. Try a sharper or closer image.")
    return {"text": text, "dialogue": looks_like_dialogue(text)}
