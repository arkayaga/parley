"""Parley desktop app: a pywebview window with a small Python API for the UI."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

# Must run before anything imports edge_tts, so a repaired engine wins.
from parley import engine_update

engine_update.activate_saved()

import webview  # noqa: E402

from parley import ocr, profiles, project, tts, updater  # noqa: E402
from parley.cache import ClipCache  # noqa: E402
from parley.paths import resource_dir  # noqa: E402
from parley.script import decode_text_file, looks_like_dialogue, parse_script  # noqa: E402
from parley.version import APP_NAME, GITHUB_REPO, VERSION  # noqa: E402

FILE_TYPES_PROJECT = ("Parley project (*.parley)",)
FILE_TYPES_TEXT = ("Text files (*.txt)", "All files (*.*)")
FILE_TYPES_IMAGE = ("Images (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff)",)


def _error(exc: Exception) -> dict:
    return {"ok": False, "error": str(exc)}


class Api:
    def __init__(self):
        self.window: webview.Window | None = None
        self.cancel = threading.Event()
        self.last: dict | None = None
        self.cache = ClipCache()
        self.update_info: dict | None = None
        self.dirty = False

    # ----- helpers -------------------------------------------------------
    def _emit(self, event: str, data) -> None:
        if self.window:
            self.window.evaluate_js(f"window.parley && parley.onEvent({json.dumps(event)}, {json.dumps(data)})")

    def _dialog(self, kind, **kwargs):
        result = self.window.create_file_dialog(kind, **kwargs)
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    # ----- start-up -------------------------------------------------------
    def init(self):
        return {
            "version": VERSION, "repo": GITHUB_REPO, "platform": sys.platform,
            "ocr": ocr.available(), "engine": engine_update.current_version(),
            "engineCustom": engine_update.is_custom(), "settings": project.load_settings(),
        }

    def voices(self):
        try:
            return {"ok": True, "voices": asyncio.run(tts.list_voices())}
        except Exception:
            return {"ok": False, "voices": tts.FALLBACK_VOICES}

    def set_settings(self, values):
        project.save_settings(values)
        return True

    def set_dirty(self, dirty):
        self.dirty = bool(dirty)

    # ----- speech ----------------------------------------------------------
    def _render(self, lines, characters, gap_ms, cancel, progress=lambda f, m: None):
        voices = {c["name"]: tts.Voice(c["voice"], int(c.get("rate", 0)), int(c.get("pitch", 0))) for c in characters}
        items = [tts.Line(l["speaker"], l["text"]) for l in lines if l["text"].strip()]
        return tts.render(items, voices, int(gap_ms), cancel, progress, self.cache)

    def generate(self, payload):
        """Render the script. Returns audio as base64 plus line timings."""
        self.cancel = threading.Event()
        cancel = self.cancel
        try:
            if payload.get("mode") == "dialogue":
                lines = [l for l in payload["lines"] if l["text"].strip()]
                if not lines:
                    raise ValueError("Add at least one line of dialogue.")
            else:
                text = payload.get("narration", "").strip()
                if not text:
                    raise ValueError("Type or paste some text first.")
                lines = [{"speaker": payload["characters"][0]["name"], "text": text}]
            result = self._render(lines, payload["characters"], payload.get("gap_ms", 400), cancel,
                                  lambda f, m: self._emit("progress", {"fraction": f, "message": m}))
        except tts.Cancelled:
            return {"ok": False, "cancelled": True}
        except tts.ServiceError as exc:
            return {"ok": False, "error": str(exc), "blocked": exc.blocked}
        except Exception as exc:
            return _error(exc)
        self.last = result
        return {"ok": True, "audio": base64.b64encode(result["mp3"]).decode("ascii"),
                "seconds": result["seconds"], "segments": result["segments"]}

    def cancel_job(self):
        self.cancel.set()

    def preview(self, voice, rate=0, pitch=0, text=None):
        sample = text or "Hello! This is how I sound. I hope you like my voice."
        try:
            result = self._render([{"speaker": "v", "text": sample}],
                                  [{"name": "v", "voice": voice, "rate": rate, "pitch": pitch}], 0, threading.Event())
        except tts.ServiceError as exc:
            return {"ok": False, "error": str(exc), "blocked": exc.blocked}
        except Exception as exc:
            return _error(exc)
        return {"ok": True, "audio": base64.b64encode(result["mp3"]).decode("ascii")}

    def save_audio(self, suggested="Parley audio"):
        if not self.last:
            return _error(ValueError("Create the audio first."))
        path = self._dialog(webview.FileDialog.SAVE, save_filename=f"{suggested}.mp3",
                            file_types=("MP3 audio (*.mp3)",))
        if not path:
            return {"ok": False}
        path = path if path.lower().endswith(".mp3") else path + ".mp3"
        try:
            Path(path).write_bytes(self.last["mp3"])
        except OSError as exc:
            return _error(exc)
        return {"ok": True, "path": path}

    def save_subtitles(self, suggested="Parley audio"):
        if not self.last:
            return _error(ValueError("Create the audio first."))
        path = self._dialog(webview.FileDialog.SAVE, save_filename=f"{suggested}.srt",
                            file_types=("Subtitles (*.srt)",))
        if not path:
            return {"ok": False}
        path = path if path.lower().endswith(".srt") else path + ".srt"
        try:
            Path(path).write_text(tts.to_srt(self.last["cues"]), "utf-8-sig")
        except OSError as exc:
            return _error(exc)
        return {"ok": True, "path": path}

    def reveal(self, path):
        try:
            if sys.platform == "win32":
                import subprocess

                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", "-R", path])
        except Exception:
            pass

    # ----- files -----------------------------------------------------------
    def open_text(self):
        path = self._dialog(webview.FileDialog.OPEN, file_types=FILE_TYPES_TEXT)
        if not path:
            return {"ok": False}
        try:
            return self.parse_text(decode_text_file(Path(path).read_bytes())) | {"name": Path(path).name}
        except Exception as exc:
            return _error(exc)

    def parse_text(self, text):
        """Classify pasted or dropped text as narration or dialogue."""
        if looks_like_dialogue(text):
            turns = parse_script(text)
            return {"ok": True, "mode": "dialogue",
                    "lines": [{"speaker": t.speaker, "text": t.text} for t in turns]}
        return {"ok": True, "mode": "narration", "text": text.strip()}

    def parse_dialogue(self, text):
        try:
            turns = parse_script(text)
        except ValueError as exc:
            return _error(exc)
        return {"ok": True, "lines": [{"speaker": t.speaker, "text": t.text} for t in turns]}

    def open_image(self):
        path = self._dialog(webview.FileDialog.OPEN, file_types=FILE_TYPES_IMAGE)
        if not path:
            return {"ok": False}
        try:
            return self._ocr(Path(path).read_bytes())
        except Exception as exc:
            return _error(exc)

    def read_image_data(self, b64):
        try:
            return self._ocr(base64.b64decode(b64))
        except Exception as exc:
            return _error(exc)

    def _ocr(self, data):
        if not ocr.available():
            raise ValueError("Reading text from images is not available on this computer.")
        result = ocr.read_image(data)
        return self.parse_text(result["text"]) if result["dialogue"] else {"ok": True, "mode": "narration",
                                                                            "text": result["text"]}

    def open_project(self):
        path = self._dialog(webview.FileDialog.OPEN, file_types=FILE_TYPES_PROJECT)
        if not path:
            return {"ok": False}
        try:
            return {"ok": True, "project": project.load(path), "path": path, "name": Path(path).stem}
        except Exception as exc:
            return _error(exc)

    def save_project(self, state, path=None):
        if not path:
            path = self._dialog(webview.FileDialog.SAVE, save_filename="Untitled.parley",
                                file_types=FILE_TYPES_PROJECT)
            if not path:
                return {"ok": False}
            path = path if path.lower().endswith(".parley") else path + ".parley"
        try:
            project.save(path, state)
        except Exception as exc:
            return _error(exc)
        return {"ok": True, "path": path, "name": Path(path).stem}

    # ----- engine repair & updates ----------------------------------------------
    def repair_engine(self):
        def live_test():
            asyncio.run(tts.synthesize("Test.", tts.Voice("en-US-AvaNeural"), threading.Event()))

        try:
            result = engine_update.repair(live_test)
        except Exception as exc:
            return _error(exc) | {"update": self._safe_check()}
        self.cache.clear()
        return {"ok": True, **result}

    def reset_engine(self):
        return {"ok": True, "version": engine_update.reset()}

    def _safe_check(self):
        try:
            self.update_info = updater.check()
        except Exception:
            self.update_info = None
        return self.update_info

    def check_update(self):
        try:
            self.update_info = updater.check()
        except Exception:
            return {"ok": False, "error": "Could not check for updates. Check your internet connection."}
        return {"ok": True, "update": self.update_info}

    def install_update(self):
        if not self.update_info:
            return _error(ValueError("No update is available."))
        if not updater.can_self_install(self.update_info):  # running from source, or no asset for this OS
            webbrowser.open(self.update_info["page"])
            return {"ok": True, "browser": True}
        try:
            updater.download_and_install(self.update_info)
        except Exception as exc:
            webbrowser.open(self.update_info["page"])
            return _error(RuntimeError(f"{exc} The download page has been opened instead."))
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return {"ok": True}

    def ask(self, title, message):
        return self.window.create_confirmation_dialog(title, message)

    # ----- voice profiles ---------------------------------------------------------
    def get_profiles(self):
        return profiles.load()

    def save_profiles(self, items):
        try:
            return {"ok": True, "profiles": profiles.save(items)}
        except Exception as exc:
            return _error(exc)

    def reset_profiles(self):
        return {"ok": True, "profiles": profiles.reset()}

    def export_profiles(self, items):
        path = self._dialog(webview.FileDialog.SAVE, save_filename="Parley voice profiles.json",
                            file_types=("Parley voice profiles (*.json)",))
        if not path:
            return {"ok": False}
        try:
            profiles.export(path, items)
        except Exception as exc:
            return _error(exc)
        return {"ok": True, "path": path}

    def import_profiles(self, items):
        path = self._dialog(webview.FileDialog.OPEN, file_types=("Parley voice profiles (*.json)",))
        if not path:
            return {"ok": False}
        try:
            merged, count = profiles.import_file(path, items)
        except Exception as exc:
            return _error(exc)
        return {"ok": True, "profiles": merged, "count": count}

    def clear_cache(self):
        self.cache.clear()
        return True

    def cache_size(self):
        return sum(p.stat().st_size for p in self.cache.folder.glob("*") if p.is_file())

    def open_url(self, url):
        if url.startswith(("https://github.com/", "https://learn.microsoft.com/")):
            webbrowser.open(url)

    def licenses(self):
        path = resource_dir() / "THIRD_PARTY_NOTICES.txt"
        try:
            return path.read_text("utf-8")
        except OSError:
            return "Third-party notices are not available in this build."

    # ----- window -----------------------------------------------------------------
    def confirm_discard(self):
        return self.window.create_confirmation_dialog(
            "Unsaved changes", "You have unsaved changes. Discard them?")


def selftest(out: str, image: str | None = None) -> None:
    """Non-interactive check used by CI on the frozen build: ``Parley.exe --selftest out.json [image]``."""
    report: dict = {"version": VERSION, "engine": engine_update.current_version(), "frozen": getattr(sys, "frozen", False)}
    try:
        result = tts.render([tts.Line("A", "Hello there."), tts.Line("B", "Hi! [pause 300ms] How are you?")],
                            {"A": tts.Voice("en-US-AvaNeural"), "B": tts.Voice("en-GB-RyanNeural")}, 300,
                            threading.Event(), cache=ClipCache(Path(os.environ.get("TEMP", "/tmp")) / "parley-selftest"))
        report["speech_seconds"] = round(result["seconds"], 2)
    except Exception as exc:
        report["speech_error"] = f"{type(exc).__name__}: {exc}"
    report["ocr_available"] = ocr.available()
    if image and report["ocr_available"]:
        try:
            report["ocr"] = ocr.read_image(Path(image).read_bytes())
        except Exception as exc:
            report["ocr_error"] = str(exc)
    report["ui_present"] = (resource_dir() / "ui" / "index.html").exists()
    Path(out).write_text(json.dumps(report, indent=2), "utf-8")


def main():
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        selftest(sys.argv[i + 1], sys.argv[i + 2] if len(sys.argv) > i + 2 else None)
        return
    api = Api()
    ui = resource_dir() / "ui" / "index.html"
    window = webview.create_window(
        APP_NAME, url=ui.as_uri(), js_api=api, width=1180, height=780, min_size=(900, 620),
        background_color="#F5F5F7", text_select=True,
    )
    api.window = window

    def on_closing():
        if api.dirty and not api.confirm_discard():
            return False
        api.cancel.set()
        return True

    window.events.closing += on_closing
    storage = str((Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Parley" / "webview")) \
        if sys.platform == "win32" else None
    webview.start(debug="--debug" in sys.argv, private_mode=False, storage_path=storage)


if __name__ == "__main__":
    main()
