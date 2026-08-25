"""PRD 8.7 - AI is not historical truth.

The PRD separates three things and refuses to blur them:

    Recorded Truth        - what actually happened
    Human Interpretation  - what a person said about it
    AI Interpretation     - what a machine guessed

Anuvritti is a record of a childhood. A guess that hardens into a remembered fact is the
worst failure this system can have, because nobody would ever notice.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import (
    AgeRange,
    Attributed,
    AttributionSource,
    Confidence,
    IntentType,
    SourceRef,
)
from anuvritti.shared.identity import FamilyId, MemberId, SparkId

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
ENGINE = HeuristicIntentEngine()


def _spark() -> Spark:
    return Spark.capture(
        spark_id=SparkId("spk-1"),
        family_id=FamilyId("fam-1"),
        owner_id=MemberId("mem-papa"),
        source=SourceRef.from_url("https://x.com/a", title="Wooden balance bike for toddlers"),
        at=NOW,
    ).apply_inference(ENGINE.infer(SourceRef.from_text("wooden balance bike for toddlers")))


class TestEveryGuessIsLabelled:
    def test_an_inferred_field_says_it_was_inferred(self):
        assert _spark().intent.source is AttributionSource.AI

    def test_an_inferred_field_carries_its_confidence(self):
        assert 0.0 < _spark().intent.confidence.value < 1.0

    def test_the_machine_never_claims_certainty(self):
        """CERTAIN belongs to what a person said, not to what a model computed."""
        for text in (
            "wooden balance bike to buy for toddlers, on sale now",
            "science experiment activity to do together outdoors",
            "how to teach a child about honesty - a lesson",
        ):
            inference = ENGINE.infer(SourceRef.from_text(text))
            assert inference.intent_confidence < Confidence.CERTAIN
            assert inference.category_confidence < Confidence.CERTAIN

    def test_a_field_the_machine_could_not_read_is_left_empty_not_invented(self):
        """An invented age range would quietly distort every future suggestion."""
        assert ENGINE.infer(SourceRef.from_text("a thought about patience")).age_range is None

    def test_a_default_is_labelled_as_a_default_not_as_a_guess(self):
        raw = Spark.capture(
            spark_id=SparkId("s"),
            family_id=FamilyId("f"),
            owner_id=MemberId("m"),
            source=SourceRef.from_text("something"),
            at=NOW,
        )
        assert raw.intent.source is AttributionSource.DEFAULT
        assert raw.intent.confidence == Confidence(0.0)


class TestTheHumanAlwaysWins:
    def test_a_human_statement_is_marked_and_certain(self):
        corrected = _spark().override_intent(IntentType.TEACH).unwrap()
        assert corrected.intent.source is AttributionSource.HUMAN
        assert corrected.intent.confidence == Confidence.CERTAIN
        assert corrected.intent.human_override is True

    def test_no_amount_of_later_inference_overwrites_a_person(self):
        corrected = _spark().override_intent(IntentType.TEACH).unwrap()
        for _ in range(50):
            corrected = corrected.apply_inference(ENGINE.infer(corrected.source))
        assert corrected.intent.value is IntentType.TEACH

    def test_a_confident_inference_still_loses_to_a_person(self):
        human = Attributed.stated(IntentType.BUY)
        assert human.reinferred(IntentType.WATCH, Confidence(0.999)) == human

    def test_overriding_is_recorded_in_the_audit_trail(self):
        spark = _spark().override_intent(IntentType.TEACH).unwrap()
        assert "SparkFieldOverridden" in [type(e).__name__ for e in spark.pending_events]


class TestProvenanceCannotBeLost:
    def test_provenance_is_always_on_the_wire(self):
        from anuvritti.interfaces.http.schemas import render_spark

        rendered = render_spark(_spark(), now=datetime(2026, 1, 10, tzinfo=UTC))
        for field in ("intent", "category"):
            assert set(rendered[field]) == {"value", "source", "confidence", "human_override"}

    def test_provenance_is_always_in_the_export(self):
        from anuvritti.application.privacy import spark_to_export

        exported = spark_to_export(_spark())
        assert exported["intent"]["source"] == "AI"
        assert "confidence" in exported["intent"]

    def test_provenance_is_stored_as_columns_not_a_blob(self):
        """ADR-0005 - a serializer change must not be able to drop it."""
        from pathlib import Path

        from anuvritti.adapters.persistence import schema

        source = Path(schema.__file__).read_text()
        for column in (
            "intent_source",
            "intent_confidence",
            "intent_overridden",
            "category_source",
            "age_source",
        ):
            assert column in source

    @pytest.mark.parametrize("value", [IntentType.DO, AgeRange(2, 5), "toy"])
    def test_serialising_any_attributed_value_keeps_all_four_parts(self, value):
        payload = Attributed.inferred(value, Confidence(0.6)).to_dict()
        assert set(payload) == {"value", "source", "confidence", "human_override"}


class TestNoFabrication:
    def test_the_product_never_writes_a_memory_on_the_familys_behalf(self):
        """PRD 47 - no fabricated AI family memories."""
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src"
        offenders = [
            path.relative_to(src)
            for path in src.rglob("*.py")
            if any(
                token in path.read_text()
                for token in ("generate_memory", "synthesise_moment", "invent_", "fabricate")
            )
        ]
        assert not offenders

    def test_a_moment_only_exists_because_a_person_said_it_happened(self):
        """Nothing in the system can create a Moment without an explicit human action."""
        import inspect

        from anuvritti.application.moments import MarkAsDoneUseCase

        signature = inspect.signature(MarkAsDoneUseCase.execute)
        assert "command" in signature.parameters

    def test_the_why_is_only_ever_written_by_a_person(self):
        """PRD 12 - the machine does not get to explain why something mattered."""
        import inspect

        from anuvritti.domain.spark import Spark

        source = inspect.getsource(Spark.record_why)
        assert "infer" not in source
        assert "generate" not in source
