"""Text handling: dialogue parsing, chunking, pause tags and text-file decoding."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 500_000
MAX_SPEAKERS = 30
CHUNK_LIMIT = 900
MAX_PAUSE_MS = 10_000

_SPEAKER_LINE = re.compile(r"^\s*([^:\n]{1,60}):\s*(.*)$")
_URL_LINE = re.compile(r"^\s*(?:https?|ftp)://", re.I)
_PAUSE_TAG = re.compile(r"\[\s*pause(?:\s+(\d+(?:\.\d+)?)\s*(ms|s)?)?\s*\]", re.I)
_SENTENCE_END = re.compile(r'[.!?]["”’\']?\s+')


@dataclass(frozen=True)
class Turn:
    speaker: str
    text: str


def parse_script(text: str) -> list[Turn]:
    """Parse ``Name: line`` dialogue. Lines without a label continue the previous turn."""
    text = text.strip()
    if not text:
        raise ValueError("Type or paste some text first.")
    if len(text) > MAX_CHARS:
        raise ValueError("A project can hold up to 500,000 characters. Split the text into several projects.")
    turns: list[Turn] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = _SPEAKER_LINE.match(line)
        if match and not _URL_LINE.match(line):
            speaker, words = (part.strip() for part in match.groups())
            if not speaker:
                raise ValueError(f"Line {number} is missing a character name.")
            turns.append(Turn(speaker, words))
        elif turns:
            last = turns[-1]
            turns[-1] = Turn(last.speaker, (last.text + " " + line.strip()).strip())
        else:
            raise ValueError(f"Line {number} should look like 'Name: Hello!'.")
    if not turns or any(not t.text for t in turns):
        raise ValueError("Every character name needs a line of text after it.")
    if len({t.speaker for t in turns}) > MAX_SPEAKERS:
        raise ValueError(f"A project can have up to {MAX_SPEAKERS} characters.")
    return turns


def looks_like_dialogue(text: str) -> bool:
    labelled = [line for line in text.splitlines() if _SPEAKER_LINE.match(line) and not _URL_LINE.match(line)]
    if len(labelled) < 2:
        return False
    try:
        parse_script(text)
    except ValueError:
        return False
    return True


def split_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Keep requests short enough to retry cheaply; prefer cutting at sentence ends."""
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    while len(text) > limit:
        ends = list(_SENTENCE_END.finditer(text[: limit + 1]))
        cut = ends[-1].end() if ends else text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def split_pauses(text: str) -> list[str | int]:
    """Split text on ``[pause]``, ``[pause 2s]`` or ``[pause 500ms]`` tags.

    Returns text pieces (str) and pause lengths in milliseconds (int). A bare
    ``[pause]`` is one second.
    """
    parts: list[str | int] = []
    pos = 0
    for match in _PAUSE_TAG.finditer(text):
        before = text[pos : match.start()].strip()
        if before:
            parts.append(before)
        amount, unit = match.groups()
        if amount is None:
            ms = 1000
        elif (unit or "s").lower() == "ms":
            ms = int(float(amount))
        else:
            ms = int(float(amount) * 1000)
        parts.append(max(0, min(ms, MAX_PAUSE_MS)))
        pos = match.end()
    rest = text[pos:].strip()
    if rest:
        parts.append(rest)
    return parts


def strip_pauses(text: str) -> str:
    return re.sub(r"\s+", " ", _PAUSE_TAG.sub(" ", text)).strip()


def decode_text_file(raw: bytes) -> str:
    if len(raw) > 2_000_000:
        raise ValueError("The text file is too large (2 MB maximum).")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")
