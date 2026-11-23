from parley.cache import ClipCache
from parley.tts import to_srt


def test_roundtrip_and_prune(tmp_path):
    cache = ClipCache(tmp_path, limit=250)
    k1, k2 = cache.key("a", "v", 0, 0), cache.key("b", "v", 0, 0)
    assert k1 != k2 and k1 == cache.key("a", "v", 0, 0)
    assert cache.get(k1) is None
    cache.put(k1, b"x" * 200, [[0, 1, "a"]])
    assert cache.get(k1) == (b"x" * 200, [[0, 1, "a"]])
    cache.put(k2, b"y" * 200, [])
    assert cache.get(k1) is None  # oldest pruned to stay under the limit
    assert cache.get(k2) is not None


def test_srt():
    srt = to_srt([{"start": 0.1, "end": 1.5, "text": "Hi."}, {"start": 61.0, "end": 3725.25, "text": "Bye."}])
    assert srt.splitlines()[:3] == ["1", "00:00:00,100 --> 00:00:01,500", "Hi."]
    assert "00:01:01,000 --> 01:02:05,250" in srt
