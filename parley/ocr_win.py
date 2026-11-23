"""Windows text recognition backend (Windows.Media.Ocr)."""
from __future__ import annotations

import asyncio


def available() -> bool:
    from winrt.windows.media.ocr import OcrEngine

    return OcrEngine.try_create_from_user_profile_languages() is not None


async def _recognize(data: bytes) -> list[str]:
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    from .ocr import merge_rows

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
    limit = OcrEngine.max_image_dimension
    if bitmap.pixel_width > limit or bitmap.pixel_height > limit:
        raise ValueError(f"The image is too large to read (max {limit} pixels per side).")
    result = await engine.recognize_async(bitmap)
    boxes = []
    for line in result.lines:
        words = list(line.words)
        if not words:
            continue
        top = min(w.bounding_rect.y for w in words)
        bottom = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
        left = min(w.bounding_rect.x for w in words)
        boxes.append((left, top, max(1.0, bottom - top), line.text))
    return merge_rows(boxes)


def recognize(data: bytes) -> list[str]:
    return asyncio.run(_recognize(data))
