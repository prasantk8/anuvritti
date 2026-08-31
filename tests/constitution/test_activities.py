"""Constitution test for offline activities (TASK-814, PRD 22, PRD 8.4, PRD 63.6).

Rule: The only screen whose success is the app closing.
Every activity must be offline, physically grounded, and end with 'Phone goes away now.'
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.constitution

ACTIVITIES_FILE = Path(__file__).parents[2] / "content" / "activities" / "activities.json"

FORBIDDEN_SCREEN_WORDS = (
    "screen",
    "watch video",
    "video",
    "scroll",
    "download",
    "app",
    "device",
    "login",
    "install",
    "swipe",
)

FORBIDDEN_GUILT_WORDS = (
    "streak",
    "badge",
    "points",
    "level",
    "score",
    "daily goal",
)


def load_activities() -> list[dict]:
    assert ACTIVITIES_FILE.is_file(), f"Activities file missing at {ACTIVITIES_FILE}"
    content = ACTIVITIES_FILE.read_text(encoding="utf-8")
    data = json.loads(content)
    assert isinstance(data, list), "Activities data must be a list"
    assert len(data) > 0, "Activities list must not be empty"
    return data


def test_activities_load_and_validate():
    activities = load_activities()
    for act in activities:
        assert "id" in act and act["id"].startswith("act-")
        assert "title" in act and len(act["title"].strip()) > 0
        assert "author" in act and len(act["author"].strip()) > 0
        assert "date" in act
        assert "steps" in act and len(act["steps"]) > 0
        assert "duration_minutes" in act and 1 <= act["duration_minutes"] <= 60


def test_every_activity_ends_with_phone_goes_away_now():
    activities = load_activities()
    for act in activities:
        assert act.get("closing") == "Phone goes away now.", (
            f"Activity {act.get('id')} must end with exactly 'Phone goes away now.'"
        )


def test_no_activity_promotes_screen_time_or_surveillance():
    activities = load_activities()
    for act in activities:
        combined_text = f"{act['title']} {' '.join(act['steps'])} {act.get('closing', '')}".lower()
        for word in FORBIDDEN_SCREEN_WORDS:
            assert word not in combined_text, (
                f"Activity {act['id']} contains screen promotion word '{word}'"
            )
        for word in FORBIDDEN_GUILT_WORDS:
            assert word not in combined_text, (
                f"Activity {act['id']} contains guilt/gamification word '{word}'"
            )
