"""Project files (.parley, JSON) and app settings."""
from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir
from .script import MAX_CHARS, MAX_SPEAKERS

FORMAT = "parley"


def validate(state: dict) -> dict:
    """Return a cleaned copy of a project state, or raise ValueError."""
    if not isinstance(state, dict) or state.get("format") != FORMAT or state.get("version") != 1:
        raise ValueError("This is not a Parley project file.")
    mode = state.get("mode")
    if mode not in ("narration", "dialogue"):
        raise ValueError("The project file is damaged (unknown mode).")
    lines = state.get("lines", [])
    chars = state.get("characters", [])
    if not isinstance(lines, list) or not isinstance(chars, list) or len(chars) > MAX_SPEAKERS:
        raise ValueError("The project file is damaged.")
    clean_lines = []
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("speaker"), str) or not isinstance(line.get("text"), str):
            raise ValueError("The project file is damaged (bad line).")
        clean_lines.append({"speaker": line["speaker"][:60], "text": line["text"]})
    clean_chars = []
    for c in chars:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("voice"), str):
            raise ValueError("The project file is damaged (bad character).")
        clean_chars.append({
            "name": c["name"][:60], "voice": c["voice"][:80],
            "rate": max(-50, min(100, int(c.get("rate", 0)))),
            "pitch": max(-50, min(50, int(c.get("pitch", 0)))),
        })
    narration = state.get("narration", "")
    if not isinstance(narration, str):
        raise ValueError("The project file is damaged.")
    if len(narration) + sum(len(l["text"]) for l in clean_lines) > MAX_CHARS:
        raise ValueError("The project is too large.")
    return {
        "format": FORMAT, "version": 1, "mode": mode, "narration": narration,
        "lines": clean_lines, "characters": clean_chars,
        "gap_ms": max(0, min(3000, int(state.get("gap_ms", 400)))),
    }


def load(path: str | Path) -> dict:
    path = Path(path)
    if path.stat().st_size > 5_000_000:
        raise ValueError("The project file is too large.")
    try:
        state = json.loads(path.read_text("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("This is not a Parley project file.") from exc
    return validate(state)


def save(path: str | Path, state: dict) -> None:
    clean = validate(state)
    Path(path).write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")


def _settings_file() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        value = json.loads(_settings_file().read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(values: dict) -> None:
    current = load_settings()
    current.update(values)
    _settings_file().write_text(json.dumps(current, ensure_ascii=False, indent=2), "utf-8")
