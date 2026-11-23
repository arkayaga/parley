"""End-to-end smoke test of the real window: loads the example, creates audio
through the JS bridge and checks the result. Run: python tests/e2e_app.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# A fresh data folder, as on a first install.
os.environ["PARLEY_DATA_DIR"] = tempfile.mkdtemp(prefix="parley-e2e-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webview  # noqa: E402

from parley import main as app  # noqa: E402

result = {}


def drive(window):
    def js(code, wait=0.0):
        time.sleep(wait)
        return window.evaluate_js(code)

    for _ in range(100):
        if js("!!(window.S || true) && document.querySelector('#accent').options.length > 0"):
            break
        time.sleep(0.2)
    js("document.querySelector('#emptyExample').click()")
    result["lines"] = js("document.querySelectorAll('.line').length", 0.3)
    result["cast"] = js("[...document.querySelectorAll('.char-name')].map(x => x.value)")
    js("document.querySelector('#createBtn').click()")
    for _ in range(300):
        time.sleep(0.2)
        if js("!document.querySelector('#playBtn').disabled"):
            break
    result["status"] = js("document.querySelector('#status').textContent")
    result["total"] = js("document.querySelector('#timeTotal').textContent")
    result["exportVisible"] = js("!document.querySelector('#exportWrap').hidden")
    time.sleep(1.5)
    result["playing"] = js("!document.querySelector('#audio').paused")
    result["highlight"] = js("document.querySelectorAll('.line.playing').length")
    js("document.querySelector('#audio').pause()")
    # edit -> stale
    js("const t=document.querySelector('.line textarea'); t.value += ' Thanks!'; t.dispatchEvent(new Event('input'))")
    result["afterEdit"] = js("document.querySelector('#createBtn').textContent")
    # voice profiles: defaults on first run, then edits must persist
    result["profilesAtStart"] = js("S.profiles.length")
    result["baristaVoice"] = js("S.cast.Barista.voice")
    js("S.cast.Customer.voice = 'en-GB-RyanNeural'; saveAsProfile(S.cast.Customer)")
    js("S.profiles.splice(S.profiles.findIndex(p => p.name === 'Pilot'), 1); persistProfiles(true)", 0.5)
    js("S.profiles.unshift({name: 'Coach', voice: 'en-US-GuyNeural', alt: null, rate: 10, pitch: 0, aliases: [], group: 'My profiles'}); persistProfiles(true)", 0.5)
    time.sleep(1)
    app_api.dirty = False
    window.destroy()


app_api = app.Api()
w = webview.create_window("Parley test", url=(app.resource_dir() / "ui" / "index.html").as_uri(), js_api=app_api,
                          width=1180, height=780)
app_api.window = w
webview.start(drive, w)
from parley import profiles  # noqa: E402

saved = {p["name"]: p for p in profiles.load()}  # what the next start of the app will see
result["savedCustomer"] = saved["Customer"]["voice"]
result["pilotDeleted"] = "Pilot" not in saved
result["coachSaved"] = saved.get("Coach", {}).get("rate")
print(json.dumps(result, indent=1))
ok = (result.get("lines") == 5 and result.get("exportVisible") and result.get("playing")
      and result.get("afterEdit") == "Update audio"
      and result["profilesAtStart"] == len(profiles.DEFAULT_PROFILES) and result["baristaVoice"] == "en-NZ-MollyNeural"
      and result["savedCustomer"] == "en-GB-RyanNeural" and result["pilotDeleted"] and result["coachSaved"] == 10)
sys.exit(0 if ok else 1)
