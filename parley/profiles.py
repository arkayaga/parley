"""Voice profiles: named characters with a remembered voice, kept across projects.

A character whose name matches a profile (or one of its aliases) gets that
voice automatically. "Student A" / "Student B" style names use the profile's
first and second (``alt``) voice, so two students never sound the same.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .project import load_settings, save_settings

MAX_PROFILES = 300


def _p(name, voice, alt=None, rate=0, pitch=0, aliases=(), group="General"):
    return {"name": name, "voice": voice, "alt": alt, "rate": rate, "pitch": pitch,
            "aliases": list(aliases), "group": group}


# Chosen for university English preparation classes: everyday roles of
# coursebook dialogues, with a deliberate mix of accents.
DEFAULT_PROFILES = [
    # People
    _p("Narrator", "en-US-AvaNeural", "en-GB-RyanNeural", aliases=["Speaker", "Announcer"]),
    _p("Woman", "en-US-EmmaNeural", "en-GB-LibbyNeural", aliases=["Lady"]),
    _p("Man", "en-GB-RyanNeural", "en-US-BrianNeural", aliases=["Gentleman"]),
    _p("Girl", "en-US-AnaNeural", "en-GB-MaisieNeural", aliases=["Daughter", "Little girl"]),
    _p("Boy", "en-US-BrianNeural", "en-US-EricNeural", rate=5, pitch=20, aliases=["Son", "Little boy", "Kid", "Child"]),
    _p("Mother", "en-AU-NatashaNeural", aliases=["Mom", "Mum", "Mommy", "Wife", "Aunt"]),
    _p("Father", "en-AU-WilliamMultilingualNeural", aliases=["Dad", "Daddy", "Husband", "Uncle"]),
    _p("Grandmother", "en-GB-SoniaNeural", rate=-10, pitch=-5, aliases=["Grandma", "Granny"]),
    _p("Grandfather", "en-US-RogerNeural", rate=-10, aliases=["Grandpa"]),
    _p("Friend", "en-US-JennyNeural", "en-US-GuyNeural", aliases=["Best friend", "Flatmate", "Housemate"]),
    _p("Neighbour", "en-IE-ConnorNeural", "en-IE-EmilyNeural", aliases=["Neighbor"]),
    # Campus
    _p("Teacher", "en-GB-SoniaNeural", "en-US-ChristopherNeural", aliases=["Instructor", "Tutor", "Lecturer"], group="Campus"),
    _p("Student", "en-US-AndrewNeural", "en-US-EmmaNeural", aliases=["Learner", "Pupil"], group="Campus"),
    _p("Professor", "en-GB-ThomasNeural", "en-US-MichelleNeural", aliases=["Prof", "Dr"], group="Campus"),
    _p("Classmate", "en-CA-LiamNeural", "en-CA-ClaraNeural", group="Campus"),
    _p("Roommate", "en-US-AriaNeural", "en-NZ-MitchellNeural", aliases=["Room mate", "Dorm mate"], group="Campus"),
    _p("Librarian", "en-IE-EmilyNeural", group="Campus"),
    _p("Advisor", "en-US-MichelleNeural", aliases=["Adviser", "Counsellor", "Counselor", "Registrar"], group="Campus"),
    # Food and shopping
    _p("Waiter", "en-US-GuyNeural", "en-GB-ThomasNeural", aliases=["Server"], group="Food & shopping"),
    _p("Waitress", "en-US-JennyNeural", "en-GB-LibbyNeural", group="Food & shopping"),
    _p("Customer", "en-US-MichelleNeural", "en-US-EricNeural", aliases=["Client", "Diner", "Shopper", "Buyer"], group="Food & shopping"),
    _p("Barista", "en-NZ-MollyNeural", "en-CA-LiamNeural", group="Food & shopping"),
    _p("Chef", "en-GB-ThomasNeural", aliases=["Cook"], group="Food & shopping"),
    _p("Shop Assistant", "en-GB-LibbyNeural", "en-US-SteffanNeural",
       aliases=["Sales Assistant", "Salesperson", "Shopkeeper", "Clerk", "Seller", "Assistant"], group="Food & shopping"),
    _p("Cashier", "en-CA-ClaraNeural", aliases=["Checkout"], group="Food & shopping"),
    # Travel
    _p("Receptionist", "en-ZA-LeahNeural", "en-IE-ConnorNeural", aliases=["Hotel Clerk", "Front Desk"], group="Travel"),
    _p("Tourist", "en-US-RogerNeural", "en-AU-NatashaNeural", aliases=["Traveller", "Traveler", "Visitor"], group="Travel"),
    _p("Tour Guide", "en-IE-ConnorNeural", aliases=["Guide"], group="Travel"),
    _p("Passenger", "en-US-SteffanNeural", "en-US-AriaNeural", group="Travel"),
    _p("Flight Attendant", "en-GB-LibbyNeural", aliases=["Steward", "Stewardess", "Cabin Crew"], group="Travel"),
    _p("Pilot", "en-US-ChristopherNeural", aliases=["Captain"], group="Travel"),
    _p("Taxi Driver", "en-AU-WilliamMultilingualNeural", aliases=["Driver", "Cab Driver"], group="Travel"),
    _p("Ticket Agent", "en-IN-NeerjaNeural", aliases=["Ticket Officer", "Agent"], group="Travel"),
    _p("Police Officer", "en-GB-RyanNeural", aliases=["Police", "Officer", "Policeman", "Policewoman"], group="Travel"),
    # Work and health
    _p("Interviewer", "en-US-MichelleNeural", "en-GB-ThomasNeural", group="Work & health"),
    _p("Applicant", "en-US-EricNeural", "en-US-AvaNeural", aliases=["Candidate", "Interviewee"], group="Work & health"),
    _p("Manager", "en-US-ChristopherNeural", "en-GB-SoniaNeural", aliases=["Boss"], group="Work & health"),
    _p("Colleague", "en-CA-ClaraNeural", "en-CA-LiamNeural", aliases=["Coworker", "Co-worker"], group="Work & health"),
    _p("Doctor", "en-US-ChristopherNeural", "en-GB-SoniaNeural", aliases=["Dentist"], group="Work & health"),
    _p("Nurse", "en-NZ-MollyNeural", group="Work & health"),
    _p("Patient", "en-US-SteffanNeural", "en-US-AriaNeural", group="Work & health"),
    _p("Pharmacist", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural", aliases=["Chemist"], group="Work & health"),
    _p("Reporter", "en-US-AriaNeural", "en-US-GuyNeural", aliases=["Journalist", "Presenter", "Host"], group="Work & health"),
]


def _clean(p: dict) -> dict:
    if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not isinstance(p.get("voice"), str):
        raise ValueError("A voice profile is damaged.")
    name = p["name"].replace(":", "").strip()[:60]
    if not name:
        raise ValueError("Every voice profile needs a name.")
    alt = p.get("alt") if isinstance(p.get("alt"), str) and p.get("alt") else None
    aliases = [a.strip()[:60] for a in p.get("aliases", []) if isinstance(a, str) and a.strip()][:20]
    return {"name": name, "voice": p["voice"][:80], "alt": alt,
            "rate": max(-50, min(100, int(p.get("rate", 0)))), "pitch": max(-50, min(50, int(p.get("pitch", 0)))),
            "aliases": aliases, "group": str(p.get("group") or "My profiles")[:40]}


def validate(profiles) -> list[dict]:
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise ValueError("The voice profile list is damaged or too long.")
    out, seen = [], set()
    for p in profiles:
        p = _clean(p)
        if p["name"].casefold() in seen:
            continue
        seen.add(p["name"].casefold())
        out.append(p)
    return out


def load() -> list[dict]:
    saved = load_settings().get("profiles")
    if saved is None:
        return copy.deepcopy(DEFAULT_PROFILES)
    try:
        return validate(saved)
    except (ValueError, TypeError):
        return copy.deepcopy(DEFAULT_PROFILES)


def save(profiles) -> list[dict]:
    clean = validate(profiles)
    save_settings({"profiles": clean})
    return clean


def reset() -> list[dict]:
    return save(copy.deepcopy(DEFAULT_PROFILES))


def export(path: str | Path, profiles) -> None:
    data = {"format": "parley-profiles", "version": 1, "profiles": validate(profiles)}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def import_file(path: str | Path, current) -> tuple[list[dict], int]:
    """Merge profiles from a file into ``current``; same names are replaced. Returns (merged, count)."""
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("That file is too large.")
    try:
        data = json.loads(path.read_text("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("That is not a Parley voice profile file.") from exc
    if not isinstance(data, dict) or data.get("format") != "parley-profiles":
        raise ValueError("That is not a Parley voice profile file.")
    incoming = validate(data.get("profiles"))
    names = {p["name"].casefold() for p in incoming}
    merged = incoming + [p for p in validate(current) if p["name"].casefold() not in names]
    return save(merged), len(incoming)
