"""Lossless MP3 assembly at the frame level.

The speech service returns every clip as CBR MPEG audio in the same format, so
clips can be joined frame by frame without decoding. Silence is made of frames
that carry no audio data (all side information zero), which every decoder
renders as digital silence. Frame counts give exact durations and offsets.
"""
from __future__ import annotations

from dataclasses import dataclass

_BITRATES = {  # (version_id, layer_id) -> kbps by index
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],  # MPEG-1 L3
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # MPEG-2 L3
    (0, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # MPEG-2.5 L3
}
_SAMPLE_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


@dataclass(frozen=True)
class FrameInfo:
    sample_rate: int
    samples: int  # samples per frame
    length: int  # bytes
    mono: bool
    version: int

    @property
    def seconds(self) -> float:
        return self.samples / self.sample_rate


def _parse_header(data: bytes, pos: int) -> FrameInfo | None:
    if pos + 4 > len(data) or data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
        return None
    b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
    version, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
    if version == 1 or layer != 1:  # reserved version, or not Layer III
        return None
    br_index, sr_index, padding = (b2 >> 4) & 0xF, (b2 >> 2) & 3, (b2 >> 1) & 1
    if br_index in (0, 15) or sr_index == 3:
        return None
    bitrate = _BITRATES[(version, layer)][br_index] * 1000
    sample_rate = _SAMPLE_RATES[version][sr_index]
    samples = 1152 if version == 3 else 576
    length = samples // 8 * bitrate // sample_rate + padding
    return FrameInfo(sample_rate, samples, length, ((b3 >> 6) & 3) == 3, version)


def _skip_id3(data: bytes) -> int:
    if data[:3] == b"ID3" and len(data) >= 10:
        size = 0
        for b in data[6:10]:
            size = (size << 7) | (b & 0x7F)
        return 10 + size
    return 0


def frames(data: bytes) -> list[tuple[int, FrameInfo]]:
    """Return (offset, info) for every audio frame, skipping tags and junk."""
    out = []
    pos = _skip_id3(data)
    while pos < len(data) - 3:
        info = _parse_header(data, pos)
        if info and pos + info.length <= len(data):
            nxt = pos + info.length
            # Require the next frame to line up (or end of data) to avoid false syncs.
            if nxt >= len(data) - 3 or _parse_header(data, nxt):
                if not _is_info_frame(data, pos, info):
                    out.append((pos, info))
                pos = nxt
                continue
        pos += 1
    return out


def _is_info_frame(data: bytes, pos: int, info: FrameInfo) -> bool:
    body = data[pos : pos + min(info.length, 64)]
    return b"Xing" in body or b"Info" in body


def duration(data: bytes) -> float:
    return sum(info.seconds for _, info in frames(data))


class Mp3Builder:
    """Concatenates clips of one MP3 format and inserts silence between them."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._header: bytes | None = None
        self._info: FrameInfo | None = None
        self._pending_ms = 0  # silence requested before the format is known
        self.seconds = 0.0

    def add_clip(self, data: bytes) -> tuple[float, float]:
        """Append a clip; returns its (start, end) time in the output."""
        found = frames(data)
        if not found:
            raise ValueError("The speech service returned no audio.")
        first_pos, first = found[0]
        if self._info is None:
            self._info = first
            self._header = data[first_pos : first_pos + 4]
            if self._pending_ms:
                self.add_silence(self._pending_ms)
                self._pending_ms = 0
        elif (first.sample_rate, first.samples, first.mono) != (
            self._info.sample_rate, self._info.samples, self._info.mono
        ):
            raise ValueError("The speech service returned audio in an unexpected format.")
        start = self.seconds
        for pos, info in found:
            self._parts.append(data[pos : pos + info.length])
            self.seconds += info.seconds
        return start, self.seconds

    def add_silence(self, ms: int) -> None:
        if ms <= 0:
            return
        if self._info is None:
            self._pending_ms += ms
            return
        frame = self._silent_frame()
        count = round(ms / 1000 / self._info.seconds)
        self._parts.append(frame * count)
        self.seconds += count * self._info.seconds

    def _silent_frame(self) -> bytes:
        assert self._header and self._info
        header = bytearray(self._header)
        header[1] |= 0x01  # no CRC
        header[2] &= ~0x02 & 0xFF  # no padding
        length = _parse_header(bytes(header) + b"\0" * 4, 0).length
        return bytes(header) + b"\0" * (length - 4)

    def build(self) -> bytes:
        return b"".join(self._parts)
