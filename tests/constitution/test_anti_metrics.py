"""TASK-1405 - The anti-metrics enforced in code.

PRD 53, PRD 8.5, PRD 46.

No streak, no daily active target, no session length goal - a test that fails
if one is ever introduced anywhere in the product or server.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_TERMS = [
    r"\bstreak\b",
    r"\bdaily_active\b",
    r"\bdau\b",
    r"\bmau\b",
    r"\bleaderboard\b",
    r"\bgamif\b",
    r"\bpoints_earned\b",
    r"\breward_points\b",
    r"\bbadge_unlocked\b",
]


def test_codebase_contains_zero_gamification_or_streak_mechanisms() -> None:
    """Scans all domain, application, and UI logic for forbidden gamification patterns."""
    scanned_extensions = {".py", ".ts", ".tsx"}
    scanned_dirs = [
        ROOT / "src",
        ROOT / "apps" / "anuvritti" / "src",
        ROOT / "apps" / "anuvritti" / "app",
    ]

    violations: list[str] = []

    for base_dir in scanned_dirs:
        if not base_dir.exists():
            continue
        for path in base_dir.rglob("*"):
            if path.is_file() and path.suffix in scanned_extensions:
                content = path.read_text(encoding="utf-8")
                for term in FORBIDDEN_TERMS:
                    matches = re.finditer(term, content, re.IGNORECASE)
                    for m in matches:
                        # Allow explicit comments/docstrings repudiating the term
                        line = content[
                            max(0, content.rfind("\n", 0, m.start())) : content.find("\n", m.end())
                        ].strip()
                        line_lower = line.lower()
                        if any(
                            phrase in line_lower
                            for phrase in (
                                "no streak",
                                "zero streak",
                                "neither has a streak",
                                "without a streak",
                                "anti-metric",
                                "refusal",
                                "not a streak",
                                "no streaks",
                            )
                        ):
                            continue
                        rel_path = path.relative_to(ROOT)
                        violations.append(f"{rel_path}: '{term}' found in line: {line.strip()}")

    assert not violations, (
        "Found forbidden gamification or engagement anti-patterns:\n" + "\n".join(violations)
    )
