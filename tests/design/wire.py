"""A real payload, built the way the HTTP edge builds one.

The design tests mostly read source and emitted CSS. This is the one place they need an
actual response, because the rule under test - "the interface is never handed the number" -
is about what a client receives, not about what the source looks like.

Built from real domain objects and rendered by the real renderer, so a change that puts the
count back on the wire fails here whatever route it takes to get there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from anuvritti.domain.return_engine import ReturnContext, ReturnEngine
from anuvritti.domain.spark import Inference, Spark
from anuvritti.domain.values import AgeRange, Confidence, IntentType, SourceRef
from anuvritti.interfaces.http.schemas import render_suggestion
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId

SAVED_AT = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)
CHILD = ChildId("ch-1")


def a_suggestion_rendered_after(*, days: int) -> dict[str, Any]:
    """One Spark, saved and then forgotten for `days`, as the parent's phone receives it."""
    now = SAVED_AT + timedelta(days=days)

    spark = Spark.capture(
        spark_id=SparkId("sp-1"),
        family_id=FamilyId("fam-1"),
        owner_id=MemberId("mem-papa"),
        subject_child_id=CHILD,
        source=SourceRef.from_url(
            "https://instagram.com/reel/balloon-rocket",
            creator="@sciencedad",
            title="Balloon rocket experiment",
        ),
        at=SAVED_AT,
    )
    spark = spark.apply_inference(
        Inference(
            title="Balloon rocket experiment",
            intent=IntentType.DO,
            intent_confidence=Confidence.HIGH,
            category="science",
            category_confidence=Confidence.MEDIUM,
            age_range=AgeRange(5, 8),
            age_confidence=Confidence.HIGH,
        )
    ).with_events_cleared()

    context = ReturnContext(
        now=now,
        child_ages={str(CHILD): 5},
        child_names={str(CHILD): "Aarav"},
        threshold=0.0,
    )
    suggestion = ReturnEngine().select([spark], context)[0]
    return render_suggestion(suggestion, now=now)


__all__ = ["a_suggestion_rendered_after"]
