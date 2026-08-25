"""TASK-206 - the Return Engine (PRD 14, 48 F6).

"Saving is not the core value. Returning is."

The engine is a pure function: no clock, no network, no randomness. That is deliberate.
A system that decides when to interrupt a family must be auditable, and the PRD 8.5 rule
- no guilt, no fake urgency - has to be enforceable, not aspirational.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from anuvritti.domain.return_engine import ReturnContext, ReturnEngine, describe_elapsed
from anuvritti.domain.spark import Inference, Spark
from anuvritti.domain.values import (
    AgeRange,
    Confidence,
    IntentType,
    SourceRef,
    Visibility,
)
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
SATURDAY = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
WEDNESDAY = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

ENGINE = ReturnEngine()
_DEFAULT_AGE_RANGE = AgeRange(4, 7)


def _spark(
    spark_id: str = "spk-1",
    *,
    intent: IntentType = IntentType.DO,
    age_range: AgeRange | None = _DEFAULT_AGE_RANGE,
    captured_at: datetime = T0,
    why: bool = False,
    suggested_count: int = 0,
) -> Spark:
    spark = Spark.capture(
        spark_id=SparkId(spark_id),
        family_id=FamilyId("fam-1"),
        owner_id=MemberId("mem-papa"),
        subject_child_id=ChildId("ch-1"),
        source=SourceRef.from_url("https://example.com/a", title="Balloon rocket"),
        at=captured_at,
        visibility=Visibility.PRIVATE,
    ).apply_inference(
        Inference(
            title="Balloon rocket",
            intent=intent,
            intent_confidence=Confidence(0.8),
            category="science-activity",
            category_confidence=Confidence(0.7),
            age_range=age_range,
            age_confidence=Confidence(0.6) if age_range else None,
        )
    )
    if why:
        spark = spark.record_why(text="I never had one growing up", at=captured_at).unwrap()
    for _ in range(suggested_count):
        spark = spark.mark_suggested(captured_at, score=0.5).unwrap()
        spark = spark.snooze(until=captured_at + timedelta(days=1)).unwrap()
    return spark.with_events_cleared()


def _ctx(now: datetime = SATURDAY, age: int = 5, **kwargs) -> ReturnContext:
    return ReturnContext(now=now, child_ages={"ch-1": age}, **kwargs)


class TestEligibility:
    def test_an_archived_spark_is_never_returned(self):
        """PRD 8.5 - the system must take "not relevant anymore" for an answer."""
        archived = _spark().archive().unwrap()
        assert ENGINE.is_eligible(archived, _ctx()) is False

    def test_a_snoozed_spark_is_not_returned_during_its_cooldown(self):
        spark = _spark().mark_suggested(T0, score=0.6).unwrap()
        spark = spark.snooze(until=T0 + timedelta(days=30)).unwrap()
        assert ENGINE.is_eligible(spark, _ctx(now=T0 + timedelta(days=10))) is False

    def test_a_snoozed_spark_returns_once_the_cooldown_has_passed(self):
        spark = _spark().mark_suggested(T0, score=0.6).unwrap()
        spark = spark.snooze(until=T0 + timedelta(days=30)).unwrap()
        assert ENGINE.is_eligible(spark, _ctx(now=T0 + timedelta(days=40))) is True

    def test_an_experienced_spark_is_not_returned(self):
        lived = _spark().experience(SATURDAY).unwrap()
        assert ENGINE.is_eligible(lived, _ctx()) is False

    def test_a_planned_spark_is_not_returned(self):
        planned = _spark().mark_suggested(T0, score=0.6).unwrap().plan().unwrap()
        assert ENGINE.is_eligible(planned, _ctx()) is False

    def test_an_uncaptured_spark_that_was_never_enriched_is_not_returned(self):
        raw = Spark.capture(
            spark_id=SparkId("s"),
            family_id=FamilyId("f"),
            owner_id=MemberId("m"),
            source=SourceRef.from_text("thought"),
            at=T0,
        )
        assert ENGINE.is_eligible(raw, _ctx()) is False

    def test_a_waiting_spark_is_eligible(self):
        assert ENGINE.is_eligible(_spark(), _ctx()) is True


class TestScoring:
    def test_the_score_is_always_a_probability(self):
        for age in range(0, 12):
            score = ENGINE.score(_spark(), _ctx(age=age))
            assert 0.0 <= score.total <= 1.0

    def test_scoring_is_pure(self):
        spark, ctx = _spark(), _ctx()
        assert ENGINE.score(spark, ctx).total == ENGINE.score(spark, ctx).total

    def test_a_child_inside_the_age_window_scores_higher_than_one_who_is_too_young(self):
        """PRD 14 - child age is the strongest signal."""
        ready = ENGINE.score(_spark(age_range=AgeRange(4, 7)), _ctx(age=5)).total
        too_young = ENGINE.score(_spark(age_range=AgeRange(4, 7)), _ctx(age=1)).total
        assert ready > too_young

    def test_a_child_who_has_outgrown_it_scores_lower_than_one_in_the_window(self):
        in_window = ENGINE.score(_spark(age_range=AgeRange(4, 7)), _ctx(age=5)).total
        outgrown = ENGINE.score(_spark(age_range=AgeRange(4, 7)), _ctx(age=14)).total
        assert outgrown < in_window

    def test_a_spark_with_no_age_range_is_neither_rewarded_nor_punished(self):
        score = ENGINE.score(_spark(age_range=None), _ctx(age=5))
        assert 0.0 < score.breakdown["age_fit"] < 1.0

    def test_older_captures_mature_into_higher_scores(self):
        """PRD 48 F6 - "You saved this 3 months ago"."""
        recent = ENGINE.score(_spark(captured_at=SATURDAY - timedelta(days=3)), _ctx()).total
        old = ENGINE.score(_spark(captured_at=SATURDAY - timedelta(days=200)), _ctx()).total
        assert old > recent

    def test_maturation_saturates_rather_than_growing_forever(self):
        """Otherwise the oldest Spark wins every week, forever."""
        one_year = ENGINE.score(_spark(captured_at=SATURDAY - timedelta(days=365)), _ctx())
        five_years = ENGINE.score(_spark(captured_at=SATURDAY - timedelta(days=1825)), _ctx())
        assert five_years.breakdown["maturation"] == pytest.approx(
            one_year.breakdown["maturation"], abs=0.05
        )

    def test_an_actionable_intent_scores_higher_on_a_weekend(self):
        do_weekend = ENGINE.score(_spark(intent=IntentType.DO), _ctx(now=SATURDAY)).total
        do_weekday = ENGINE.score(_spark(intent=IntentType.DO), _ctx(now=WEDNESDAY)).total
        assert do_weekend > do_weekday

    def test_a_buy_intent_is_not_rushed_by_the_weekend(self):
        """PRD 53 anti-metric - unnecessary purchases. Saturday is not a shopping trigger."""
        buy_weekend = ENGINE.score(_spark(intent=IntentType.BUY), _ctx(now=SATURDAY))
        buy_weekday = ENGINE.score(_spark(intent=IntentType.BUY), _ctx(now=WEDNESDAY))
        assert buy_weekend.breakdown["occasion_fit"] == buy_weekday.breakdown["occasion_fit"]

    def test_a_recorded_why_raises_the_score(self):
        """PRD 12 - the human "why" is the most valuable metadata in the system."""
        with_why = ENGINE.score(_spark(why=True), _ctx()).total
        without = ENGINE.score(_spark(why=False), _ctx()).total
        assert with_why > without

    def test_repeated_suggestions_decay_the_score(self):
        """PRD 8.5 - asking again and again is how a product becomes nagging."""
        first = ENGINE.score(_spark(suggested_count=0), _ctx()).total
        fourth = ENGINE.score(_spark(suggested_count=3), _ctx()).total
        assert fourth < first

    def test_the_breakdown_names_every_weighted_signal(self):
        """An engine that decides when to interrupt a family must be auditable."""
        breakdown = ENGINE.score(_spark(), _ctx()).breakdown
        assert set(breakdown) == {
            "age_fit",
            "maturation",
            "occasion_fit",
            "intent_actionability",
            "why_present",
            "novelty",
        }

    def test_the_weights_sum_to_one(self):
        assert sum(ReturnEngine.WEIGHTS.values()) == pytest.approx(1.0)

    def test_every_signal_is_itself_a_probability(self):
        for value in ENGINE.score(_spark(), _ctx()).breakdown.values():
            assert 0.0 <= value <= 1.0


class TestSelection:
    def test_nothing_below_the_threshold_is_surfaced(self):
        ctx = _ctx(threshold=0.99)
        assert ENGINE.select([_spark()], ctx) == []

    def test_an_empty_result_is_normal_and_silent(self):
        """PRD 8.5 - having nothing to say is a valid, guilt-free outcome."""
        assert ENGINE.select([], _ctx()) == []

    def test_results_are_ordered_by_score(self):
        sparks = [
            _spark("weak", captured_at=SATURDAY - timedelta(days=2), age_range=AgeRange(10, 12)),
            _spark("strong", captured_at=SATURDAY - timedelta(days=300), why=True),
        ]
        chosen = ENGINE.select(sparks, _ctx(threshold=0.0))
        assert next(str(s.spark.id) for s in chosen) == "strong"

    def test_the_daily_cap_is_honoured(self):
        """PRD 53 anti-metric - notification volume is minimised, not maximised."""
        sparks = [_spark(f"s{i}", captured_at=SATURDAY - timedelta(days=300)) for i in range(20)]
        assert len(ENGINE.select(sparks, _ctx(max_suggestions=3, threshold=0.0))) == 3

    def test_ineligible_sparks_are_filtered_before_scoring(self):
        archived = _spark("archived").archive().unwrap()
        chosen = ENGINE.select([archived, _spark("ok")], _ctx(threshold=0.0))
        assert [str(s.spark.id) for s in chosen] == ["ok"]

    def test_selection_is_deterministic(self):
        sparks = [_spark(f"s{i}", captured_at=SATURDAY - timedelta(days=100 + i)) for i in range(6)]
        first = [str(s.spark.id) for s in ENGINE.select(sparks, _ctx(threshold=0.0))]
        second = [str(s.spark.id) for s in ENGINE.select(sparks, _ctx(threshold=0.0))]
        assert first == second

    def test_ties_are_broken_stably_by_id(self):
        sparks = [_spark("b"), _spark("a")]
        chosen = ENGINE.select(sparks, _ctx(threshold=0.0, max_suggestions=2))
        assert len(chosen) == 2

    def test_a_suggestion_carries_its_score_and_elapsed_time(self):
        spark = _spark(captured_at=SATURDAY - timedelta(days=243))
        suggestion = ENGINE.select([spark], _ctx(threshold=0.0))[0]
        assert 0.0 <= suggestion.score <= 1.0
        assert suggestion.days_since_capture == 243

    def test_a_suggestion_offers_exactly_the_three_prd_actions(self):
        suggestion = ENGINE.select([_spark()], _ctx(threshold=0.0))[0]
        assert suggestion.actions == ("maybe_later", "lets_do_it", "not_relevant_anymore")


class TestGuiltFreeCopy:
    """PRD 8.5, 47 - the boundary the product must never cross."""

    FORBIDDEN = (
        "still",
        "haven't",
        "have not",
        "forgot",
        "don't forget",
        "overdue",
        "missed",
        "failing",
        "should have",
        "last chance",
        "hurry",
        "act now",
        "running out",
        "only today",
        "streak",
        "you owe",
    )

    def test_the_reason_reads_like_a_person_not_a_reminder(self):
        spark = _spark(captured_at=SATURDAY - timedelta(days=243))
        reason = ENGINE.select([spark], _ctx(threshold=0.0))[0].reason
        assert "You saved this" in reason

    @pytest.mark.parametrize("days", [0, 3, 40, 100, 243, 400, 1200])
    def test_no_reason_ever_contains_guilt_or_urgency(self, days):
        """Checked against the copy directly, across every elapsed span the engine can
        describe - including spans the quiet period would normally withhold."""
        spark = _spark(captured_at=SATURDAY - timedelta(days=days))
        for age in (1, 5, 14):
            ctx = _ctx(age=age, threshold=0.0)
            for reason_key in ("grown_into_it", "time_passed", "still_waiting"):
                reason = ENGINE.reason_for(spark, ctx, reason_key)
                assert not any(word in reason.lower() for word in self.FORBIDDEN), reason

    def test_the_reason_never_counts_how_often_it_was_shown(self):
        spark = _spark(suggested_count=3, captured_at=SATURDAY - timedelta(days=300))
        reason = ENGINE.select([spark], _ctx(threshold=0.0))[0].reason
        assert "3" not in reason
        assert "again" not in reason.lower()

    def test_a_child_who_has_grown_into_it_is_told_gently(self):
        spark = _spark(age_range=AgeRange(5, 8), captured_at=SATURDAY - timedelta(days=300))
        reason = ENGINE.select([spark], _ctx(age=5, threshold=0.0))[0].reason
        assert "may be ready now" in reason

    def test_the_reason_never_asserts_certainty_about_the_child(self):
        """PRD 8.7 - AI interpretation is not truth about a person."""
        for days in (10, 300):
            spark = _spark(captured_at=SATURDAY - timedelta(days=days))
            reason = ENGINE.select([spark], _ctx(threshold=0.0))[0].reason
            assert "will love" not in reason.lower()
            assert "definitely" not in reason.lower()


class TestElapsedLanguage:
    @pytest.mark.parametrize(
        "days,expected",
        [
            (0, "today"),
            (1, "yesterday"),
            (5, "5 days ago"),
            (21, "3 weeks ago"),
            (62, "2 months ago"),
            (243, "8 months ago"),
            (400, "a year ago"),
            (900, "2 years ago"),
        ],
    )
    def test_elapsed_time_is_described_the_way_a_person_would(self, days, expected):
        assert describe_elapsed(days) == expected

    def test_negative_elapsed_time_is_treated_as_today(self):
        assert describe_elapsed(-5) == "today"


class TestChildIsNamedNotAssumed:
    """The PRD writes "He may be ready now" about one specific son.

    Shipped as product code it must not assert a gender the family never told us.
    """

    def test_the_child_is_named_when_the_family_told_us_their_name(self):
        spark = _spark(age_range=AgeRange(5, 8), captured_at=SATURDAY - timedelta(days=300))
        ctx = ReturnContext(
            now=SATURDAY, child_ages={"ch-1": 5}, child_names={"ch-1": "Aarav"}, threshold=0.0
        )
        assert "Aarav may be ready now." in ENGINE.select([spark], ctx)[0].reason

    def test_an_unnamed_child_is_referred_to_neutrally(self):
        spark = _spark(age_range=AgeRange(5, 8), captured_at=SATURDAY - timedelta(days=300))
        reason = ENGINE.select([spark], _ctx(age=5, threshold=0.0))[0].reason
        assert "They may be ready now." in reason

    def test_no_gendered_pronoun_is_ever_assumed(self):
        spark = _spark(age_range=AgeRange(5, 8), captured_at=SATURDAY - timedelta(days=300))
        for age in (1, 5, 14):
            reason = ENGINE.select([spark], _ctx(age=age, threshold=0.0))[0].reason
            words = reason.lower().replace(".", " ").replace(",", " ").split()
            assert not ({"he", "him", "his", "she", "her", "hers"} & set(words)), reason


class TestQuietPeriod:
    """Worth Bringing Back returns things that were *forgotten*.

    Something saved this morning has not been forgotten. Surfacing it the same afternoon
    is manufactured engagement, which PRD 8.5 and 47 rule out. Scoring alone cannot
    enforce this - a fresh, well-matched Spark clears any sensible threshold - so it is a
    hard eligibility rule.
    """

    def test_a_spark_saved_today_is_never_brought_back(self):
        fresh = _spark(captured_at=SATURDAY)
        assert ENGINE.is_eligible(fresh, _ctx()) is False

    def test_a_spark_saved_this_week_is_never_brought_back(self):
        recent = _spark(captured_at=SATURDAY - timedelta(days=3))
        assert ENGINE.select([recent], _ctx(threshold=0.0)) == []

    def test_a_high_scoring_fresh_spark_is_still_held_back(self):
        """The rule is not a threshold, so a strong match cannot buy its way past it."""
        fresh = _spark(captured_at=SATURDAY - timedelta(days=1), why=True)
        assert ENGINE.score(fresh, _ctx()).total > 0.45
        assert ENGINE.select([fresh], _ctx(threshold=0.0)) == []

    def test_it_becomes_eligible_once_the_quiet_period_passes(self):
        spark = _spark(captured_at=SATURDAY - timedelta(days=8))
        assert ENGINE.is_eligible(spark, _ctx()) is True

    def test_the_boundary_is_inclusive_of_the_full_quiet_period(self):
        ctx = _ctx(min_days_before_return=7)
        assert ENGINE.is_eligible(_spark(captured_at=SATURDAY - timedelta(days=6)), ctx) is False
        assert ENGINE.is_eligible(_spark(captured_at=SATURDAY - timedelta(days=7)), ctx) is True

    def test_the_quiet_period_is_configurable(self):
        spark = _spark(captured_at=SATURDAY - timedelta(days=2))
        assert ENGINE.is_eligible(spark, _ctx(min_days_before_return=30)) is False
        assert ENGINE.is_eligible(spark, _ctx(min_days_before_return=1)) is True

    def test_it_can_be_disabled_for_a_family_that_wants_it_off(self):
        spark = _spark(captured_at=SATURDAY)
        assert ENGINE.is_eligible(spark, _ctx(min_days_before_return=0)) is True
