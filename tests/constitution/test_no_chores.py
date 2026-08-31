"""TASK-803 - The unsorted pile is a first-class state (PRD 8.5, PRD 8.8).

An uncategorised, untagged Spark returns on time alone.
The product never nags the parent to sort, file, or 'clean up' their vault.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.domain.return_engine import ReturnContext, ReturnEngine
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId

pytestmark = pytest.mark.constitution

FAMILY = FamilyId("fam-1")
CHILD = ChildId("ch-1")
PAPA = MemberId("mem-papa")
T_PAST = datetime(2025, 8, 25, 10, 0, tzinfo=UTC)
T_NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


def test_unsorted_spark_returns_on_time_alone():
    # Spark captured with minimal text, no category, no tags, no why
    spark = Spark.capture(
        spark_id=SparkId("spk-raw-1"),
        family_id=FAMILY,
        owner_id=PAPA,
        source=SourceRef.from_text("Look at this cool rock"),
        at=T_PAST,
        subject_child_id=CHILD,
    )

    engine = ReturnEngine()
    context = ReturnContext(now=T_NOW, child_ages={"ch-1": 4})
    score = engine.score(spark, context)

    # Scored positively on time / maturation alone
    assert score.total > 0.0
    reason = engine.reason_for(spark, context, score.reason_key)
    assert reason is not None
    assert "saved" in reason.lower() or "ago" in reason.lower() or "good" in reason.lower()


def test_no_inbox_zero_or_sorting_nag():
    # Verify copy across system contains no chore or sorting demands
    forbidden = (
        "uncategorized",
        "needs sorting",
        "organize your",
        "inbox zero",
        "clean up your",
        "items waiting for tags",
    )
    from pathlib import Path

    source = (Path(__file__).parents[2] / "apps" / "anuvritti" / "src" / "said.ts").read_text()
    for word in forbidden:
        assert word not in source.lower()
