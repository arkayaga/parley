"""Talks to the real speech service. Run with: pytest -m live"""
import threading

import pytest

from parley import audio, tts

pytestmark = pytest.mark.live


def test_dialogue_render(tmp_path):
    lines = [tts.Line("Barista", "Hi! What can I get you? [pause 500ms] We have fresh croissants."),
             tts.Line("Customer", "A latte, please.")]
    voices = {"Barista": tts.Voice("en-US-AvaNeural"), "Customer": tts.Voice("en-GB-RyanNeural", rate=10, pitch=-5)}
    from parley.cache import ClipCache

    result = tts.render(lines, voices, 400, threading.Event(), cache=ClipCache(tmp_path))
    assert result["seconds"] > 2
    assert audio.duration(result["mp3"]) == pytest.approx(result["seconds"])
    s = result["segments"]
    assert [x["line"] for x in s] == [0, 1] and s[0]["end"] < s[1]["start"]
    assert len(result["cues"]) >= 3


def test_voices_list():
    import asyncio

    voices = asyncio.run(tts.list_voices())
    assert any(v["ShortName"] == "en-US-AvaNeural" for v in voices)
