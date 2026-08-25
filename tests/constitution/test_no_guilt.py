"""PRD 8.5 - No guilt.

    "Not as notification spam. Not as guilt."

The Return Engine is the only part of the product that speaks first. Everything it can
say is checked here, exhaustively, across every state it can reach.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anuvritti.domain import return_engine
from anuvritti.domain.return_engine import ReturnContext, ReturnEngine, describe_elapsed
from anuvritti.domain.spark import Inference, Spark
from anuvritti.domain.values import AgeRange, Confidence, IntentType, SourceRef
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId

SRC = Path(__file__).resolve().parents[2] / "src"
ENGINE = ReturnEngine()
NOW = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)

#: Vocabulary that turns a reminder into an accusation.
GUILT = (
    "still",
    "haven't",
    "have not",
    "hasn't",
    "forgot",
    "forget",
    "overdue",
    "missed",
    "failing",
    "failed",
    "should have",
    "you owe",
    "neglect",
    "behind",
    "lapsed",
    "broke your",
    "let down",
    "disappointed",
)

#: Vocabulary that manufactures urgency the family did not feel.
URGENCY = (
    "last chance",
    "hurry",
    "act now",
    "running out",
    "only today",
    "expires",
    "don't miss",
    "limited time",
    "final",
    "urgent",
    "immediately",
    "right now!",
)

#: Mechanics that make a person feel measured.
SCOREKEEPING = ("streak", "score", "rank", "leaderboard", "points", "level up", "badge")


def _spark(*, days_old: int, why: str | None, intent: IntentType, ages: AgeRange | None) -> Spark:
    spark = Spark.capture(
        spark_id=SparkId("spk-1"),
        family_id=FamilyId("fam-1"),
        owner_id=MemberId("mem-papa"),
        subject_child_id=ChildId("ch-1"),
        source=SourceRef.from_text("something"),
        at=NOW - timedelta(days=days_old),
    ).apply_inference(
        Inference(
            title="something",
            intent=intent,
            intent_confidence=Confidence(0.7),
            category="thing",
            category_confidence=Confidence(0.5),
            age_range=ages,
            age_confidence=Confidence(0.6) if ages else None,
        )
    )
    if why:
        spark = spark.record_why(text=why, at=NOW - timedelta(days=days_old)).unwrap()
    return spark.with_events_cleared()


def _every_reason_the_product_can_say() -> list[str]:
    """Every string the Return Engine is capable of showing a parent."""
    reasons: list[str] = []
    for days_old in (0, 1, 8, 40, 100, 243, 400, 1200, 4000):
        for why in (None, "I never had one growing up"):
            for intent in IntentType.v0_set():
                for ages in (None, AgeRange(2, 4), AgeRange(5, 8), AgeRange(10, 14)):
                    spark = _spark(days_old=days_old, why=why, intent=intent, ages=ages)
                    for age in (0, 3, 5, 9, 17):
                        for names in ({}, {"ch-1": "Aarav"}):
                            ctx = ReturnContext(
                                now=NOW, child_ages={"ch-1": age}, child_names=names
                            )
                            score = ENGINE.score(spark, ctx)
                            reasons.append(ENGINE.reason_for(spark, ctx, score.reason_key))
    return reasons


ALL_REASONS = _every_reason_the_product_can_say()


class TestTheWordsItCanSay:
    def test_the_corpus_is_actually_exhaustive(self):
        assert len(ALL_REASONS) > 1000
        assert len(set(ALL_REASONS)) > 5

    @pytest.mark.parametrize("word", GUILT)
    def test_no_reason_ever_blames_the_parent(self, word):
        offenders = [r for r in ALL_REASONS if word in r.lower()]
        assert not offenders, f"PRD 8.5 forbids guilt; {word!r} appears in {offenders[:2]}"

    @pytest.mark.parametrize("word", URGENCY)
    def test_no_reason_ever_manufactures_urgency(self, word):
        offenders = [r for r in ALL_REASONS if word in r.lower()]
        assert not offenders, f"PRD 8.5 forbids fake urgency; {word!r} appears in {offenders[:2]}"

    @pytest.mark.parametrize("word", SCOREKEEPING)
    def test_no_reason_ever_keeps_score(self, word):
        offenders = [r for r in ALL_REASONS if word in r.lower()]
        assert not offenders, f"PRD 47 forbids scorekeeping; {word!r} appears in {offenders[:2]}"

    def test_no_reason_ever_uses_an_exclamation_mark(self):
        """A product that shouts at a parent about their child has lost the plot."""
        assert not [r for r in ALL_REASONS if "!" in r]

    def test_no_reason_ever_predicts_how_the_child_will_react(self):
        """PRD 8.7 - the machine does not get to claim it knows a child."""
        for claim in ("will love", "will enjoy", "definitely", "guaranteed", "needs this"):
            assert not [r for r in ALL_REASONS if claim in r.lower()]

    def test_no_reason_ever_counts_anything_at_the_parent(self):
        """Not "3rd reminder", not "2 of 5 done", not any tally."""
        for tally in ("reminder", "of 5", "times", "attempt", "again"):
            assert not [r for r in ALL_REASONS if tally in r.lower()]

    def test_elapsed_time_is_always_stated_softly(self):
        for days in range(0, 4000, 37):
            phrase = describe_elapsed(days)
            assert not any(w in phrase for w in ("ago!", "already", "finally"))


class TestTheMechanics:
    def test_the_daily_cap_exists_and_is_small(self):
        """PRD 53 anti-metric - notification volume is minimised, not maximised."""
        assert ReturnContext(now=NOW, child_ages={}).max_suggestions <= 5

    def test_declining_permanently_is_honoured_forever(self):
        spark = _spark(days_old=100, why=None, intent=IntentType.DO, ages=None)
        spark = spark.mark_suggested(NOW, score=0.6).unwrap().archive().unwrap()
        far_future = ReturnContext(now=NOW + timedelta(days=36500), child_ages={})
        assert ENGINE.is_eligible(spark, far_future) is False

    def test_maybe_later_is_measured_in_weeks_not_hours(self):
        from anuvritti.config.settings import load_settings

        settings = load_settings({"ANUVRITTI_ENV": "test"}).unwrap()
        assert settings.snooze_cooldown_days >= 7

    def test_nothing_is_surfaced_before_it_could_be_forgotten(self):
        fresh = _spark(days_old=0, why=None, intent=IntentType.DO, ages=None)
        assert ENGINE.is_eligible(fresh, ReturnContext(now=NOW, child_ages={})) is False

    def test_repeated_suggestions_always_decay(self):
        spark = _spark(days_old=200, why=None, intent=IntentType.DO, ages=None)
        ctx = ReturnContext(now=NOW, child_ages={})
        scores = []
        for _ in range(4):
            scores.append(ENGINE.score(spark, ctx).total)
            spark = spark.mark_suggested(NOW, score=0.5).unwrap()
            spark = spark.snooze(until=NOW + timedelta(days=1)).unwrap()
        assert scores == sorted(scores, reverse=True)


class TestTheCodeItself:
    def test_the_engine_has_no_concept_of_a_streak_or_a_score_to_display(self):
        tree = ast.parse(inspect.getsource(return_engine))
        names = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Name | ast.Attribute)
        }
        forbidden = ("streak", "consecutive_days", "completion_rate", "guilt", "nag")
        assert not [n for n in names if any(w in n.lower() for w in forbidden)]

    def test_no_module_anywhere_schedules_a_push_notification(self):
        """V0 has no notification channel at all. Nothing can spam what does not exist."""
        offenders = [
            path.relative_to(SRC)
            for path in SRC.rglob("*.py")
            if any(
                token in path.read_text().lower()
                for token in ("push_notification", "send_push", "apns", "fcm_token")
            )
        ]
        assert not offenders
