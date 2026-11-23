import json

import pytest

from parley import profiles


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PARLEY_DATA_DIR", str(tmp_path / "data"))


def test_defaults_are_valid_and_unique():
    clean = profiles.validate(profiles.DEFAULT_PROFILES)
    assert len(clean) == len(profiles.DEFAULT_PROFILES)
    names = [n.casefold() for p in clean for n in [p["name"], *p["aliases"]]]
    assert len(names) == len(set(names)), "a name or alias is used by two profiles"


def test_load_save_reset():
    assert profiles.load()[0]["name"] == "Narrator"
    mine = [{"name": "Coach", "voice": "en-US-GuyNeural"}]
    profiles.save(mine)
    assert [p["name"] for p in profiles.load()] == ["Coach"]
    assert len(profiles.reset()) == len(profiles.DEFAULT_PROFILES)


def test_validation():
    with pytest.raises(ValueError):
        profiles.validate([{"name": "", "voice": "x"}])
    out = profiles.validate([{"name": "A:", "voice": "v", "rate": 500, "pitch": -99}, {"name": "a", "voice": "w"}])
    assert out == [{"name": "A", "voice": "v", "alt": None, "rate": 100, "pitch": -50, "aliases": [], "group": "My profiles"}]


def test_export_import_merges(tmp_path):
    path = tmp_path / "p.json"
    profiles.export(path, [{"name": "Teacher", "voice": "en-US-GuyNeural"}])
    merged, count = profiles.import_file(path, profiles.load())
    assert count == 1
    teacher = [p for p in merged if p["name"] == "Teacher"]
    assert len(teacher) == 1 and teacher[0]["voice"] == "en-US-GuyNeural"
    path.write_text(json.dumps({"format": "other"}))
    with pytest.raises(ValueError):
        profiles.import_file(path, [])
