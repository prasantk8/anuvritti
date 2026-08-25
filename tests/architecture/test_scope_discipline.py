"""TASK-104 - PRD 49 non-scope must stay out of the codebase.

Scope creep in a family-memory product is not a schedule problem, it is an ethics problem.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

#: PRD 49 - deliberately not built in V0. Matched as identifiers, not prose.
FORBIDDEN_CONCEPTS = {
    "location tracking": r"\b(gps_|geofence|track_location|last_known_location)\w*",
    "screen monitoring": r"\b(screen_time_monitor|app_usage_log|keystroke)\w*",
    "voice cloning": r"\b(clone_voice|voice_clone|synthesi[sz]e_voice)\w*",
    "marketplace": r"\b(checkout|add_to_cart|affiliate_link|price_alert)\w*",
    "leaderboards": r"\b(leaderboard|parent_rank|family_rank)\w*",
    "streaks": r"\b(streak_count|current_streak|streak_broken)\w*",
    "behavioural scoring": r"\b(child_score|behaviour_score|good_child)\w*",
}


@pytest.mark.parametrize("concept,pattern", sorted(FORBIDDEN_CONCEPTS.items()))
def test_v0_non_scope_is_absent_from_source(concept: str, pattern: str):
    offenders = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if re.search(pattern, path.read_text(), re.IGNORECASE)
    ]
    assert not offenders, f"PRD 49 forbids {concept} in V0, found in {offenders}"
