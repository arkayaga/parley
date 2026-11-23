"""Speech synthesis on top of edge-tts: retries, cancellation, caching, assembly."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from . import audio
from .cache import ClipCache
from .script import split_pauses, split_text

FALLBACK_VOICES = [
    {"ShortName": "en-US-AvaNeural", "Gender": "Female", "Locale": "en-US"},
    {"ShortName": "en-US-AndrewNeural", "Gender": "Male", "Locale": "en-US"},
    {"ShortName": "en-US-AriaNeural", "Gender": "Female", "Locale": "en-US"},
    {"ShortName": "en-US-GuyNeural", "Gender": "Male", "Locale": "en-US"},
    {"ShortName": "en-US-JennyNeural", "Gender": "Female", "Locale": "en-US"},
    {"ShortName": "en-GB-SoniaNeural", "Gender": "Female", "Locale": "en-GB"},
    {"ShortName": "en-GB-RyanNeural", "Gender": "Male", "Locale": "en-GB"},
    {"ShortName": "en-AU-NatashaNeural", "Gender": "Female", "Locale": "en-AU"},
    {"ShortName": "en-AU-WilliamNeural", "Gender": "Male", "Locale": "en-AU"},
]


class Cancelled(Exception):
    pass


class ServiceError(RuntimeError):
    """The speech service could not be used. ``blocked`` means it refused us (e.g. HTTP 403)."""

    def __init__(self, message: str, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked


@dataclass
class Line:
    speaker: str
    text: str


@dataclass
class Voice:
    voice: str
    rate: int = 0  # percent, -50..100
    pitch: int = 0  # Hz, -50..50


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled()


async def _cancellable(coro, cancel: threading.Event):
    task = asyncio.create_task(coro)
    try:
        while not task.done():
            _check(cancel)
            await asyncio.sleep(0.05)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _is_blocked(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return "403" in text or "Handshake" in text


async def list_voices() -> list[dict]:
    import edge_tts

    voices = await asyncio.wait_for(edge_tts.list_voices(), 25)
    keep = ("ShortName", "Gender", "Locale", "FriendlyName")
    return sorted(({k: v.get(k, "") for k in keep} for v in voices), key=lambda v: (v["Locale"], v["ShortName"]))


async def _stream(text: str, voice: Voice) -> tuple[bytes, list]:
    import edge_tts

    speech = edge_tts.Communicate(
        text, voice.voice, rate=f"{voice.rate:+d}%", pitch=f"{voice.pitch:+d}Hz",
        connect_timeout=15, receive_timeout=35,
    )
    data, cues = bytearray(), []
    async for chunk in speech.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
        elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
            cues.append([chunk["offset"] / 1e7, (chunk["offset"] + chunk["duration"]) / 1e7, chunk["text"]])
    return bytes(data), cues


async def synthesize(text: str, voice: Voice, cancel: threading.Event, retry_note=lambda n: None):
    last: Exception | None = None
    for attempt in range(3):
        _check(cancel)
        try:
            data, cues = await _cancellable(asyncio.wait_for(_stream(text, voice), 110), cancel)
            if not audio.frames(data):
                raise RuntimeError("empty audio")
            return data, cues
        except Cancelled:
            raise
        except Exception as exc:
            last = exc
            if _is_blocked(exc):
                break  # retrying a refused handshake will not help
            if attempt < 2:
                retry_note(attempt + 1)
                await _cancellable(asyncio.sleep(1.5 * (attempt + 1)), cancel)
    blocked = last is not None and _is_blocked(last)
    message = (
        "The speech service refused the connection. Parley can repair its speech engine automatically."
        if blocked
        else "Could not reach the speech service. Check your internet connection and try again."
    )
    raise ServiceError(f"{message}\n\nDetails: {type(last).__name__}: {str(last)[:200]}", blocked=blocked)


def render(lines: list[Line], voices: dict[str, Voice], gap_ms: int, cancel: threading.Event,
           progress=lambda fraction, message: None, cache: ClipCache | None = None) -> dict:
    """Synthesize every line and assemble one MP3.

    Returns {"mp3": bytes, "seconds": float, "segments": [{"line", "start", "end"}],
    "cues": [{"start", "end", "text"}]} with times in seconds.
    """
    cache = cache or ClipCache()
    jobs = []  # (line index, piece) where piece is text or pause ms
    for index, line in enumerate(lines):
        if line.speaker not in voices:
            raise ValueError(f"Choose a voice for {line.speaker}.")
        for piece in split_pauses(line.text):
            if isinstance(piece, int):
                jobs.append((index, piece))
            else:
                jobs.extend((index, chunk) for chunk in split_text(piece))
    if not any(isinstance(piece, str) for _, piece in jobs):
        raise ValueError("There is nothing to read aloud yet.")
    total_text = sum(1 for _, piece in jobs if isinstance(piece, str))

    builder = audio.Mp3Builder()
    segments: dict[int, dict] = {}
    cues = []
    done = 0
    previous_line = None

    async def run():
        nonlocal done, previous_line
        for index, piece in jobs:
            _check(cancel)
            if previous_line is not None and index != previous_line and gap_ms:
                builder.add_silence(gap_ms)
            previous_line = index
            start = builder.seconds
            if isinstance(piece, int):
                builder.add_silence(piece)
            else:
                voice = voices[lines[index].speaker]
                key = cache.key(piece, voice.voice, voice.rate, voice.pitch)
                hit = cache.get(key)
                if hit:
                    data, clip_cues = hit
                else:
                    progress(done / total_text, f"Reading line {index + 1} of {len(lines)}")
                    data, clip_cues = await synthesize(
                        piece, voice, cancel,
                        lambda n: progress(done / total_text, f"Connection hiccup, retrying ({n}/2)…"),
                    )
                    cache.put(key, data, clip_cues)
                clip_start, clip_end = builder.add_clip(data)
                sentence_cues = [c for c in clip_cues if c] or [[0, clip_end - clip_start, piece]]
                for c_start, c_end, c_text in sentence_cues:
                    cues.append({"start": clip_start + c_start, "end": min(clip_start + c_end, clip_end),
                                 "text": c_text})
                done += 1
                progress(done / total_text, f"Reading line {index + 1} of {len(lines)}")
            seg = segments.setdefault(index, {"line": index, "start": start, "end": builder.seconds})
            seg["end"] = builder.seconds

    asyncio.run(run())
    _check(cancel)
    return {"mp3": builder.build(), "seconds": builder.seconds,
            "segments": [segments[i] for i in sorted(segments)], "cues": cues}


def to_srt(cues: list[dict]) -> str:
    def stamp(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    blocks = [f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1)]
    return "\n".join(blocks)
