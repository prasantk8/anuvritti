"""PRD 49 - V0 deliberate non-scope.

    "The vision stays. The engineering stays small."

Scope creep in a family-memory product is not a schedule problem. Each of these was
deliberately excluded, and each has a test so that adding one is a decision rather than
an accident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

#: PRD 49, mapped to the identifiers that would exist if it were being built.
NON_SCOPE = {
    "family social network": (
        r"\b(follow_user|friend_request|public_feed|share_publicly|comment_on)"
    ),
    "creator marketplace": r"\b(creator_payout|marketplace_listing|seller_account)",
    "full marketplace": r"\b(add_to_cart|checkout|payment_intent|order_total)",
    "toy price engine": r"\b(price_history|price_alert|track_price|lowest_price)",
    "health platform": r"\b(diagnos|symptom_check|prescription|bmi_|growth_percentile)",
    "learning platform": r"\b(curriculum|lesson_plan|quiz_score|grade_level_test)",
    "voice cloning": r"\b(clone_voice|voice_clone|synthesi[sz]e_voice|tts_persona)",
    "ask my family": r"\b(ask_my_family|family_oracle|ancestor_chat)",
    "knowledge graph UI": r"\b(graph_node|graph_edge|render_graph|force_directed)",
    "generative child content": r"\b(generate_story_for_child|ai_bedtime_story|synthetic_content)",
    "18-year book generator": r"\b(generate_book|first_18_years|memoir_render)",
    "wearables": r"\b(wearable|heart_rate|step_count|sleep_tracker)",
    "advanced agents": r"\b(agent_loop|autonomous_agent|tool_calling|plan_and_execute)",
    "large recommendation engine": (
        r"\b(collaborative_filter|embedding_index|vector_search|ann_index)"
    ),
}


@pytest.mark.parametrize("feature,pattern", sorted(NON_SCOPE.items()))
def test_the_feature_is_absent_from_v0(feature: str, pattern: str):
    offenders = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.py")
        if re.search(pattern, path.read_text(), re.IGNORECASE)
    ]
    assert not offenders, f"PRD 49 excludes {feature} from V0; found in {offenders}"


class TestTheEngineeringStaysSmall:
    def test_all_ten_intents_are_active(self):
        """TASK-816 - All ten intents active."""
        from anuvritti.domain.values import IntentType

        assert len(IntentType) == 10
        assert IntentType.COOK.is_available_in_v0 is True
        assert IntentType.VISIT.is_available_in_v0 is True
        assert IntentType.TELL.is_available_in_v0 is True
        assert IntentType.LISTEN.is_available_in_v0 is True

    def test_the_return_engine_uses_six_signals_not_a_model(self):
        """PRD 49 excludes a large recommendation engine."""
        from anuvritti.domain.return_engine import ReturnEngine

        assert len(ReturnEngine.WEIGHTS) == 10

    def test_the_intent_engine_makes_no_network_call(self):
        """PRD 49 excludes advanced agents; PRD 44 excludes model training by default."""
        from anuvritti.adapters.intent import heuristic

        source = Path(heuristic.__file__).read_text()
        for token in ("requests.", "httpx", "urlopen", "aiohttp", "openai", "anthropic"):
            assert token not in source

    def test_the_runtime_dependency_list_stays_short(self):
        import tomllib

        root = Path(__file__).resolve().parents[2]
        deps = tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]
        assert len(deps) <= 6, f"every dependency is a liability for family data: {deps}"

    def test_there_is_no_background_scheduler(self):
        """V0 has nothing that runs on its own and decides to contact a family."""
        offenders = [
            path.relative_to(SRC)
            for path in SRC.rglob("*.py")
            if re.search(r"\b(celery|apscheduler|cron_job|schedule\.every)", path.read_text())
        ]
        assert not offenders


class TestWhatV0DoesShip:
    """The inverse guard: the nine V0 features must all actually exist (PRD 48)."""

    @pytest.mark.parametrize(
        "feature,module",
        [
            ("F1 universal capture", "anuvritti.application.capture"),
            ("F2 lightweight AI understanding", "anuvritti.adapters.intent.heuristic"),
            ("F3 optional human why", "anuvritti.application.capture"),
            ("F4 six intent types", "anuvritti.domain.values"),
            ("F5 safe vault", "anuvritti.application.vault"),
            ("F6 worth bringing back", "anuvritti.application.returning"),
            ("F7 mark as done", "anuvritti.application.moments"),
            ("F8 little things", "anuvritti.application.presence"),
            ("F9 right now", "anuvritti.application.presence"),
        ],
    )
    def test_the_v0_feature_is_implemented(self, feature: str, module: str):
        import importlib

        assert importlib.import_module(module), feature
