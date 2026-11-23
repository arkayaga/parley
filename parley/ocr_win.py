"""Read text from an image with the OCR engine built into Windows 10/11.

Nothing leaves the computer. On other systems ``available()`` is False.
"""
from __future__ import annotations

import asyncio
import re
import sys

from .script import looks_like_dialogue

_PREFIX = re.compile(r"^([A-Za-z][A-Za-z .’'\-]{0,35})\s*[:：]\s*(.*)$")
MAX_BYTES = 30 * 1024 * 1024


def available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from winrt.windows.media.ocr import OcrEngine

        return OcrEngine.try_create_from_user_profile_languages() is not None
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


async def _recognize(data: bytes) -> list[str]:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(data)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise ValueError("Windows has no text recognition language installed.")
    if bitmap.pixel_width > OcrEngine.max_image_dimension or bitmap.pixel_height > OcrEngine.max_image_dimension:
        raise ValueError(f"The image is too large to read (max {OcrEngine.max_image_dimension} pixels per side).")
    result = await engine.recognize_async(bitmap)
    return [line.text for line in result.lines]


def read_image(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("Images can be up to 30 MB.")
    try:
        lines = asyncio.run(_recognize(data))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The image could not be read. Try a PNG or JPG file.") from exc
    text = "\n".join(clean_line(l) for l in lines if l.strip())
    if not text.strip():
        raise ValueError("No readable text was found. Try a sharper or closer image.")
    return {"text": text, "dialogue": looks_like_dialogue(text)}
