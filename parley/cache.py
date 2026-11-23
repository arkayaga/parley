"""Disk cache of synthesized clips, so unchanged lines are never re-requested."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .paths import data_dir

LIMIT_BYTES = 300 * 1024 * 1024


class ClipCache:
    def __init__(self, folder: Path | None = None, limit: int = LIMIT_BYTES):
        self.folder = folder or data_dir() / "cache"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.limit = limit

    @staticmethod
    def key(text: str, voice: str, rate: int, pitch: int) -> str:
        raw = json.dumps([text, voice, rate, pitch], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str):
        audio, meta = self.folder / f"{key}.mp3", self.folder / f"{key}.json"
        try:
            data = audio.read_bytes()
            cues = json.loads(meta.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        audio.touch()
        return data, cues

    def put(self, key: str, data: bytes, cues: list) -> None:
        try:
            (self.folder / f"{key}.json").write_text(json.dumps(cues), "utf-8")
            (self.folder / f"{key}.mp3").write_bytes(data)
            self._prune()
        except OSError:
            pass  # caching is an optimisation; never fail a job over it

    def _prune(self) -> None:
        files = sorted(self.folder.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        while files and total > self.limit:
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
            oldest.with_suffix(".json").unlink(missing_ok=True)

    def clear(self) -> None:
        for path in self.folder.glob("*"):
            path.unlink(missing_ok=True)
