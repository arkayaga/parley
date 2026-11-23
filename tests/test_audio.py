import shutil
import subprocess

import pytest

from parley import audio

HEADER = bytes.fromhex("fff364c4")  # MPEG-2 Layer III, 48 kbps, 24 kHz, mono (what the service returns)


def clip(n_frames: int) -> bytes:
    return (HEADER + b"\x11" * 140) * n_frames


def test_frame_parsing_and_duration():
    data = clip(50)
    found = audio.frames(data)
    assert len(found) == 50
    assert found[0][1].length == 144
    assert audio.duration(data) == pytest.approx(50 * 0.024)


def test_skips_id3_and_junk():
    tag = b"ID3\x04\x00\x00\x00\x00\x00\x05" + b"abcde"
    assert len(audio.frames(tag + b"junk" + clip(10))) == 10


def test_builder_offsets_and_silence():
    b = audio.Mp3Builder()
    b.add_silence(240)  # before the format is known: applied before the first clip
    s1 = b.add_clip(clip(10))
    b.add_silence(480)
    s2 = b.add_clip(clip(5))
    assert s1 == pytest.approx((0.24, 0.48))
    assert s2 == pytest.approx((0.96, 1.08))
    out = b.build()
    assert len(audio.frames(out)) == 10 + 10 + 20 + 5
    assert audio.duration(out) == pytest.approx(b.seconds)


def test_rejects_non_audio():
    with pytest.raises(ValueError):
        audio.Mp3Builder().add_clip(b"not audio at all")


@pytest.mark.skipif(not shutil.which("afinfo"), reason="macOS afinfo not available")
def test_real_decoder_accepts_output(tmp_path):
    b = audio.Mp3Builder()
    b.add_clip(clip(20))
    b.add_silence(1000)
    b.add_clip(clip(20))
    path = tmp_path / "out.mp3"
    path.write_bytes(b.build())
    info = subprocess.run(["afinfo", str(path)], capture_output=True, text=True).stdout
    assert "24000 Hz" in info
