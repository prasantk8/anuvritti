"""The Return Engine (PRD 14, 48 F6).

    "Saving is not the core value. Returning is."

Deliberately a pure function of (spark, context). No clock, no network, no randomness,
no model. Three reasons:

* A system that decides when to interrupt a family should be auditable line by line.
* PRD 8.5 ("no guilt, no fake urgency") has to be testable, not aspirational.
* PRD 49 rules out a "large recommendation engine" in V0. Six signals is enough to prove
  the thesis, and enough to explain to the one father using it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType

#: The three actions PRD 48 F6 names. There is no fourth, and none of them is a nag.
ACTIONS: Final[tuple[str, str, str]] = ("maybe_later", "lets_do_it", "not_relevant_anymore")

_NEUTRAL = 0.5
_SATURDAY = 5


@dataclass(frozen=True, slots=True)
class ReturnContext:
    """Everything the engine is allowed to know. Nothing here is a tracked signal."""

    now: datetime
    child_ages: Mapping[str, int]
    child_names: Mapping[str, str] = field(default_factory=dict)
    child_birthdays: Mapping[str, int] = field(default_factory=dict)
    child_interests: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    upcoming_events: tuple[str, ...] = field(default_factory=tuple)
    season: str | None = None
    max_suggestions: int = 3
    threshold: float = 0.45
    maturation_horizon_days: int = 180
    min_days_before_return: int = 7

    @property
    def is_weekend(self) -> bool:
        return self.now.weekday() >= _SATURDAY

    def age_of(self, child_id: str | None) -> int | None:
        return self.child_ages.get(child_id) if child_id else None

    def name_of(self, child_id: str | None) -> str | None:
        return self.child_names.get(child_id) if child_id else None


@dataclass(frozen=True, slots=True)
class Score:
    """A score plus the reason it is that score."""

    total: float
    breakdown: Mapping[str, float]
    reason_key: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One thing worth bringing back, and the words to bring it back with."""

    spark: Spark
    score: float
    reason: str
    reason_key: str
    days_since_capture: int
    actions: tuple[str, ...] = field(default=ACTIONS)


def describe_elapsed(days: int) -> str:
    """Say how long it has been the way a person would say it.

    Precision here would be a tell that a machine is speaking. "8 months ago" is what a
    father would say; "243 days ago" is what a database would say.
    """
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{round(days / 7)} weeks ago"
    if days < 335:
        return f"{round(days / 30.44)} months ago"
    if days < 550:
        return "a year ago"
    return f"{round(days / 365.25)} years ago"


class ReturnEngine:
    """Scores what may have become relevant, and says so without applying pressure."""

    #: PRD 14 signals and TASK-815 seasonal, birthday, interest, and event signals.
    WEIGHTS: Final[Mapping[str, float]] = {
        "age_fit": 0.25,
        "maturation": 0.15,
        "occasion_fit": 0.10,
        "season_fit": 0.15,
        "birthday_fit": 0.10,
        "interest_fit": 0.10,
        "event_fit": 0.05,
        "intent_actionability": 0.05,
        "why_present": 0.03,
        "novelty": 0.02,
    }

    # ------------------------------------------------------------ eligibility
    def is_eligible(self, spark: Spark, ctx: ReturnContext) -> bool:
        """Hard rules, applied before any scoring."""
        if not spark.status.is_returnable:
            return False
        if spark.days_since_capture(ctx.now) < ctx.min_days_before_return:
            return False
        return not spark.is_snoozed_at(ctx.now)

    # ---------------------------------------------------------------- scoring
    def score(self, spark: Spark, ctx: ReturnContext) -> Score:
        age = ctx.age_of(str(spark.subject_child_id) if spark.subject_child_id else None)
        days = spark.days_since_capture(ctx.now)

        signals = {
            "age_fit": self._age_fit(spark, age),
            "maturation": self._maturation(days, ctx.maturation_horizon_days),
            "occasion_fit": self._occasion_fit(spark, ctx),
            "season_fit": self._season_fit(spark, ctx),
            "birthday_fit": self._birthday_fit(spark, ctx),
            "interest_fit": self._interest_fit(spark, ctx),
            "event_fit": self._event_fit(spark, ctx),
            "intent_actionability": 1.0 if spark.intent.value.is_immediately_actionable else 0.4,
            "why_present": 1.0 if spark.why else 0.0,
            "novelty": self._novelty(spark),
        }
        total = sum(self.WEIGHTS[name] * value for name, value in signals.items())
        reason_key = self._reason_key(spark, age, days, signals)
        return Score(
            total=min(1.0, max(0.0, total)),
            breakdown=signals,
            reason_key=reason_key,
        )

    def _current_season(self, ctx: ReturnContext) -> str:
        if ctx.season:
            return ctx.season.lower()
        month = ctx.now.month
        if month in (12, 1, 2):
            return "winter"
        if month in (3, 4, 5):
            return "spring"
        if month in (6, 7, 8):
            return "summer"
        return "autumn"

    def _spark_text_corpus(self, spark: Spark) -> str:
        cat_val = (
            spark.category.value if hasattr(spark.category, "value") else str(spark.category or "")
        )
        tags_str = " ".join(t.lower() for t in spark.tags)
        return f"{spark.title.lower()} {tags_str} {str(cat_val).lower()}"

    def _season_fit(self, spark: Spark, ctx: ReturnContext) -> float:
        season = self._current_season(ctx)
        season_keywords = {
            "winter": ("winter", "snow", "cold", "cocoa", "holiday", "ice", "sled"),
            "spring": ("spring", "bloom", "garden", "flower", "rain", "puddle"),
            "summer": ("summer", "beach", "swim", "sunshine", "pool", "waterpark"),
            "autumn": ("autumn", "fall", "leaves", "harvest", "pumpkin"),
        }
        text_corpus = self._spark_text_corpus(spark)
        active_keywords = season_keywords.get(season, ())
        if any(kw in text_corpus for kw in active_keywords):
            return 1.0
        for other_season, kws in season_keywords.items():
            if other_season != season and any(kw in text_corpus for kw in kws):
                return 0.2
        return _NEUTRAL

    def _birthday_fit(self, spark: Spark, ctx: ReturnContext) -> float:
        child_id = str(spark.subject_child_id) if spark.subject_child_id else None
        if not child_id or child_id not in ctx.child_birthdays:
            return _NEUTRAL
        birth_month = ctx.child_birthdays[child_id]
        if ctx.now.month != birth_month:
            return _NEUTRAL
        text_corpus = self._spark_text_corpus(spark)
        if any(kw in text_corpus for kw in ("birthday", "gift", "party", "turning", "present")):
            return 1.0
        return _NEUTRAL

    def _interest_fit(self, spark: Spark, ctx: ReturnContext) -> float:
        child_id = str(spark.subject_child_id) if spark.subject_child_id else None
        if not child_id or child_id not in ctx.child_interests:
            return _NEUTRAL
        interests = [i.lower().strip() for i in ctx.child_interests[child_id] if i.strip()]
        if not interests:
            return _NEUTRAL
        text_corpus = self._spark_text_corpus(spark)
        if any(interest in text_corpus for interest in interests):
            return 1.0
        return _NEUTRAL

    def _event_fit(self, spark: Spark, ctx: ReturnContext) -> float:
        if not ctx.upcoming_events:
            return _NEUTRAL
        text_corpus = self._spark_text_corpus(spark)
        for event in ctx.upcoming_events:
            ev_clean = event.lower().replace("_", " ")
            if ev_clean in text_corpus or any(part in text_corpus for part in ev_clean.split()):
                return 1.0
        return _NEUTRAL

    def _age_fit(self, spark: Spark, age: int | None) -> float:
        """The strongest signal: has this child grown into it yet? (PRD 14)"""
        if spark.age_range is None or age is None:
            return _NEUTRAL
        window = spark.age_range.value
        if window.contains(age):
            return 1.0
        years_early = window.years_until(age)
        if years_early > 0:
            return max(0.0, 1.0 - (years_early * 0.35))
        years_late = age - window.max_years
        return max(0.1, 0.6 - (years_late * 0.1))

    def _maturation(self, days: int, horizon: int) -> float:
        return min(1.0, max(0, days) / horizon)

    def _occasion_fit(self, spark: Spark, ctx: ReturnContext) -> float:
        if spark.intent.value is IntentType.BUY:
            return _NEUTRAL
        if not spark.intent.value.is_immediately_actionable:
            return _NEUTRAL
        return 1.0 if ctx.is_weekend else 0.4

    def _novelty(self, spark: Spark) -> float:
        return 1.0 / (1.0 + spark.suggested_count)

    def _reason_key(
        self,
        spark: Spark,
        age: int | None,
        days: int,
        signals: Mapping[str, float] | None = None,
    ) -> str:
        if signals:
            if signals.get("event_fit", 0.0) >= 0.9:
                return "event_fit"
            if signals.get("birthday_fit", 0.0) >= 0.9:
                return "birthday_coming"
            if signals.get("interest_fit", 0.0) >= 0.9:
                return "child_interest"
            if signals.get("season_fit", 0.0) >= 0.9:
                return "season_fit"
        if spark.age_range is not None and age is not None and spark.age_range.value.contains(age):
            return "grown_into_it"
        if days >= 60:
            return "time_passed"
        return "still_waiting"

    # -------------------------------------------------------------- selection
    def select(self, sparks: Iterable[Spark], ctx: ReturnContext) -> list[Suggestion]:
        """Choose what is worth bringing back. Returning nothing is a good outcome."""
        scored: list[tuple[float, str, Spark, Score]] = []
        for spark in sparks:
            if not self.is_eligible(spark, ctx):
                continue
            result = self.score(spark, ctx)
            if result.total < ctx.threshold:
                continue
            scored.append((result.total, str(spark.id), spark, result))

        # Descending by score, then by id so the order is stable and reproducible.
        scored.sort(key=lambda row: (-row[0], row[1]))

        return [
            Suggestion(
                spark=spark,
                score=total,
                reason=self.reason_for(spark, ctx, result.reason_key),
                reason_key=result.reason_key,
                days_since_capture=spark.days_since_capture(ctx.now),
            )
            for total, _, spark, result in scored[: ctx.max_suggestions]
        ]

    # ------------------------------------------------------------------ copy
    def reason_for(self, spark: Spark, ctx: ReturnContext, reason_key: str) -> str:
        elapsed = describe_elapsed(spark.days_since_capture(ctx.now))
        opening = "You saved this today." if elapsed == "today" else f"You saved this {elapsed}."

        parts = [opening]
        if spark.why and spark.why.text:
            parts.append(f"You said: “{spark.why.text}”")
        if reason_key == "grown_into_it":
            parts.append(self._readiness_line(spark, ctx))
        elif reason_key == "birthday_coming":
            parts.append("With their birthday coming up this month.")
        elif reason_key == "child_interest":
            parts.append("They have been into this lately.")
        elif reason_key == "season_fit":
            parts.append("Good for this time of year.")
        elif reason_key == "event_fit":
            parts.append("Look outside tonight or good for today.")
        return " ".join(parts)

    def _readiness_line(self, spark: Spark, ctx: ReturnContext) -> str:
        child_id = str(spark.subject_child_id) if spark.subject_child_id else None
        name = ctx.name_of(child_id)
        return f"{name} may be ready now." if name else "They may be ready now."
