"""TASK-203 - the Spark aggregate.

A Spark is "something that made a person think: I want to remember this for us" (PRD 9).
Its lifecycle is a state machine, its AI fields carry provenance, and a human correction
is permanent. Illegal transitions are values, never exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from anuvritti.domain.events import (
    SparkArchived,
    SparkCaptured,
    SparkEnriched,
    SparkFieldOverridden,
    SparkPlanned,
    SparkSnoozed,
    SparkSuggested,
    SparkWhyRecorded,
)
from anuvritti.domain.spark import Inference, Spark
from anuvritti.domain.values import (
    AgeRange,
    AttributionSource,
    Confidence,
    IntentType,
    SourceKind,
    SourceRef,
    SparkStatus,
    Visibility,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MemberId, SparkId

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
REEL = SourceRef.from_url(
    "https://instagram.com/reel/abc", creator="@sciencedad", title="Balloon rocket"
)


def _capture(**kwargs) -> Spark:
    defaults = {
        "spark_id": SparkId("spk-1"),
        "family_id": FamilyId("fam-1"),
        "owner_id": MemberId("mem-papa"),
        "subject_child_id": ChildId("ch-1"),
        "source": REEL,
        "note": None,
        "visibility": Visibility.PRIVATE,
        "at": T0,
    }
    return Spark.capture(**{**defaults, **kwargs})


def _inference() -> Inference:
    return Inference(
        title="Balloon rocket",
        intent=IntentType.DO,
        intent_confidence=Confidence(0.8),
        age_range=AgeRange(4, 7),
        age_confidence=Confidence(0.6),
        category="science-activity",
        category_confidence=Confidence(0.7),
        tags=("science", "outdoor"),
    )


def _enriched() -> Spark:
    return _capture().apply_inference(_inference())


def _through_to(status: SparkStatus) -> Spark:
    """Drive a Spark to the requested status by the legal path."""
    spark = _enriched()
    if status is SparkStatus.WAITING:
        return spark
    if status is SparkStatus.RELEVANT:
        return spark.mark_relevant().unwrap()
    if status is SparkStatus.SUGGESTED:
        return spark.mark_suggested(T0 + timedelta(days=200), score=0.7).unwrap()
    if status is SparkStatus.PLANNED:
        return _through_to(SparkStatus.SUGGESTED).plan().unwrap()
    if status is SparkStatus.EXPERIENCED:
        return _through_to(SparkStatus.PLANNED).experience(T0 + timedelta(days=210)).unwrap()
    if status is SparkStatus.REMEMBERED:
        return _through_to(SparkStatus.EXPERIENCED).remember().unwrap()
    if status is SparkStatus.ARCHIVED:
        return spark.archive().unwrap()
    raise AssertionError(status)


class TestCapture:
    def test_a_new_spark_starts_captured(self):
        assert _capture().status is SparkStatus.CAPTURED

    def test_capture_records_who_saved_it_and_who_it_is_for(self):
        """PRD 45 - owner and subject are never conflated."""
        spark = _capture()
        assert spark.owner_id == MemberId("mem-papa")
        assert spark.subject_child_id == ChildId("ch-1")

    def test_capture_needs_no_form(self):
        """PRD 11 - target capture time is under ten seconds."""
        spark = _capture(subject_child_id=None, note=None)
        assert spark.status is SparkStatus.CAPTURED
        assert spark.why is None

    def test_the_title_falls_back_to_the_source_before_ai_runs(self):
        assert _capture().title == "Balloon rocket"

    def test_capture_defaults_to_the_most_private_visibility(self):
        assert _capture(visibility=None).visibility is Visibility.PRIVATE

    def test_capture_defaults_the_intent_to_remember(self):
        """Before the engine speaks, the honest default is 'I want to remember this'."""
        spark = _capture()
        assert spark.intent.value is IntentType.REMEMBER
        assert spark.intent.source is AttributionSource.DEFAULT

    def test_capture_emits_a_spark_captured_event(self):
        events = _capture().pending_events
        assert isinstance(events[0], SparkCaptured)
        assert events[0].source_kind is SourceKind.URL

    def test_the_capture_event_carries_no_family_content(self):
        """docs/contracts/events.md - the audit log is not a shadow archive."""
        payload = _capture(note="he will love this").pending_events[0].payload()
        assert "note" not in payload
        assert not any("love" in str(v) for v in payload.values())

    def test_a_spark_keeps_its_meaning_when_the_link_rots(self):
        """PRD 43 - a Spark must never become empty because the internet changed."""
        assert _capture().retains_meaning_without_network is True

    def test_a_bare_link_with_no_context_is_flagged_as_fragile(self):
        spark = _capture(source=SourceRef.from_url("https://instagram.com/reel/xyz"))
        assert spark.retains_meaning_without_network is False


class TestInference:
    def test_applying_inference_moves_the_spark_to_waiting(self):
        assert _enriched().status is SparkStatus.WAITING

    def test_inferred_fields_carry_ai_provenance(self):
        """PRD 13, 42 - value, source, confidence, human_override."""
        spark = _enriched()
        assert spark.intent.value is IntentType.DO
        assert spark.intent.source is AttributionSource.AI
        assert spark.intent.confidence == Confidence(0.8)
        assert spark.intent.human_override is False

    def test_inference_fills_age_category_tags_and_title(self):
        spark = _enriched()
        assert spark.age_range is not None
        assert spark.age_range.value == AgeRange(4, 7)
        assert spark.category.value == "science-activity"
        assert spark.tags == ("science", "outdoor")

    def test_inference_emits_an_enriched_event(self):
        assert any(isinstance(e, SparkEnriched) for e in _enriched().pending_events)

    def test_reinference_updates_fields_the_human_has_not_touched(self):
        improved = _enriched().apply_inference(
            Inference(
                title="Balloon rocket",
                intent=IntentType.WATCH,
                intent_confidence=Confidence(0.9),
                age_range=AgeRange(5, 8),
                age_confidence=Confidence(0.7),
                category="science-activity",
                category_confidence=Confidence(0.8),
                tags=("science",),
            )
        )
        assert improved.intent.value is IntentType.WATCH

    def test_reinference_never_overwrites_a_human_correction(self):
        """PRD 13 - human override always wins."""
        corrected = _enriched().override_intent(IntentType.TEACH).unwrap()
        reinferred = corrected.apply_inference(_inference())
        assert reinferred.intent.value is IntentType.TEACH
        assert reinferred.intent.human_override is True

    def test_inference_on_an_archived_spark_is_a_no_op(self):
        archived = _through_to(SparkStatus.ARCHIVED)
        assert archived.apply_inference(_inference()).status is SparkStatus.ARCHIVED


class TestHumanOverride:
    def test_overriding_intent_marks_the_field_as_human(self):
        spark = _enriched().override_intent(IntentType.BUY).unwrap()
        assert spark.intent.value is IntentType.BUY
        assert spark.intent.source is AttributionSource.HUMAN
        assert spark.intent.confidence == Confidence.CERTAIN

    def test_overriding_emits_an_audit_event_naming_the_field(self):
        spark = _enriched().override_intent(IntentType.BUY).unwrap()
        event = next(e for e in spark.pending_events if isinstance(e, SparkFieldOverridden))
        assert event.field == "intent"

    def test_overriding_the_age_range_is_permanent(self):
        spark = _enriched().override_age_range(AgeRange(2, 3)).unwrap()
        assert spark.apply_inference(_inference()).age_range.value == AgeRange(2, 3)  # type: ignore[union-attr]

    def test_a_v1_only_intent_cannot_be_selected_in_v0(self):
        """PRD 48 F4 - six intents. The seventh is a V1 decision, not a runtime accident."""
        err = _enriched().override_intent(IntentType.COOK).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_overriding_category_is_accepted(self):
        assert _enriched().override_category("toy").unwrap().category.value == "toy"

    def test_a_blank_category_override_is_rejected(self):
        assert _enriched().override_category("  ").unwrap_err().code is ErrorCode.VALIDATION_FAILED


class TestWhyLayer:
    def test_recording_a_written_why_attaches_it(self):
        """PRD 12 - the most valuable human metadata in the system."""
        spark = _enriched().record_why(text="I never had one growing up", at=T0).unwrap()
        assert spark.why is not None
        assert spark.why.text == "I never had one growing up"

    def test_recording_a_voice_why_stores_the_media_reference(self):
        spark = _enriched().record_why(voice_media_id="med-9", at=T0).unwrap()
        assert spark.why.voice_media_id == "med-9"  # type: ignore[union-attr]

    def test_why_requires_either_text_or_voice(self):
        err = _enriched().record_why(at=T0).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_blank_why_text_is_rejected(self):
        assert _enriched().record_why(text="   ", at=T0).is_err()

    def test_why_may_be_recorded_at_any_point_in_the_lifecycle(self):
        """PRD 12 - the product asks occasionally, not on a schedule the user must obey."""
        for status in (SparkStatus.WAITING, SparkStatus.PLANNED, SparkStatus.EXPERIENCED):
            assert _through_to(status).record_why(text="because", at=T0).is_ok()

    def test_recording_why_emits_an_event_without_the_text(self):
        spark = _enriched().record_why(text="private thing", at=T0).unwrap()
        event = next(e for e in spark.pending_events if isinstance(e, SparkWhyRecorded))
        assert "private thing" not in str(event.payload())
        assert event.has_voice is False

    def test_a_later_why_replaces_the_earlier_one(self):
        spark = _enriched().record_why(text="first", at=T0).unwrap()
        updated = spark.record_why(text="second", at=T0 + timedelta(days=1)).unwrap()
        assert updated.why.text == "second"  # type: ignore[union-attr]


class TestLifecycle:
    def test_a_waiting_spark_can_become_relevant(self):
        assert _through_to(SparkStatus.RELEVANT).status is SparkStatus.RELEVANT

    def test_a_relevant_spark_can_be_suggested(self):
        assert _through_to(SparkStatus.SUGGESTED).status is SparkStatus.SUGGESTED

    def test_suggesting_records_when_and_how_often(self):
        spark = _through_to(SparkStatus.SUGGESTED)
        assert spark.suggested_count == 1
        assert spark.last_suggested_at == T0 + timedelta(days=200)

    def test_suggesting_emits_an_event_carrying_the_score(self):
        event = next(
            e
            for e in _through_to(SparkStatus.SUGGESTED).pending_events
            if isinstance(e, SparkSuggested)
        )
        assert event.score == 0.7
        assert event.days_since_capture == 200

    def test_lets_do_it_plans_the_spark(self):
        spark = _through_to(SparkStatus.PLANNED)
        assert spark.status is SparkStatus.PLANNED
        assert any(isinstance(e, SparkPlanned) for e in spark.pending_events)

    def test_maybe_later_snoozes_without_guilt(self):
        """PRD 8.5 - 'maybe later' must mean later, not tomorrow."""
        until = T0 + timedelta(days=230)
        spark = _through_to(SparkStatus.SUGGESTED).snooze(until=until).unwrap()
        assert spark.status is SparkStatus.WAITING
        assert spark.snoozed_until == until
        assert any(isinstance(e, SparkSnoozed) for e in spark.pending_events)

    def test_not_relevant_anymore_archives_permanently(self):
        spark = _through_to(SparkStatus.SUGGESTED).archive().unwrap()
        assert spark.status is SparkStatus.ARCHIVED
        assert any(isinstance(e, SparkArchived) for e in spark.pending_events)

    def test_a_planned_spark_becomes_experienced(self):
        assert _through_to(SparkStatus.EXPERIENCED).status is SparkStatus.EXPERIENCED

    def test_something_can_be_marked_done_without_ever_being_suggested(self):
        """Real life does not wait for a notification."""
        spark = _enriched().experience(T0 + timedelta(days=3))
        assert spark.unwrap().status is SparkStatus.EXPERIENCED

    def test_an_experienced_spark_can_be_remembered(self):
        assert _through_to(SparkStatus.REMEMBERED).status is SparkStatus.REMEMBERED


class TestIllegalTransitions:
    def test_an_archived_spark_cannot_be_suggested(self):
        err = _through_to(SparkStatus.ARCHIVED).mark_suggested(T0, score=0.9).unwrap_err()
        assert err.code is ErrorCode.SPARK_ARCHIVED

    def test_an_archived_spark_cannot_be_planned(self):
        assert (
            _through_to(SparkStatus.ARCHIVED).plan().unwrap_err().code is ErrorCode.SPARK_ARCHIVED
        )

    def test_an_archived_spark_cannot_be_experienced(self):
        assert _through_to(SparkStatus.ARCHIVED).experience(T0).is_err()

    def test_an_unenriched_spark_cannot_be_suggested(self):
        err = _capture().mark_suggested(T0, score=0.9).unwrap_err()
        assert err.code is ErrorCode.SPARK_INVALID_TRANSITION

    def test_an_experienced_spark_cannot_be_suggested_again(self):
        err = _through_to(SparkStatus.EXPERIENCED).mark_suggested(T0, score=0.9).unwrap_err()
        assert err.code is ErrorCode.SPARK_INVALID_TRANSITION

    def test_a_remembered_spark_is_terminal(self):
        remembered = _through_to(SparkStatus.REMEMBERED)
        assert remembered.plan().is_err()
        assert remembered.experience(T0).is_err()

    def test_only_an_experienced_spark_can_be_remembered(self):
        assert _enriched().remember().unwrap_err().code is ErrorCode.SPARK_INVALID_TRANSITION

    def test_a_waiting_spark_cannot_be_planned_without_being_suggested(self):
        assert _enriched().plan().is_err()

    def test_snoozing_something_that_was_never_suggested_is_rejected(self):
        assert _enriched().snooze(until=T0 + timedelta(days=30)).is_err()

    def test_a_snooze_into_the_past_is_rejected(self):
        err = _through_to(SparkStatus.SUGGESTED).snooze(until=T0 - timedelta(days=1)).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_the_error_names_the_status_it_refused_from(self):
        err = _capture().plan().unwrap_err()
        assert err.details["status"] == "CAPTURED"


class TestImmutabilityAndEvents:
    def test_transitions_never_mutate_the_original(self):
        spark = _enriched()
        spark.mark_relevant()
        assert spark.status is SparkStatus.WAITING

    def test_events_accumulate_across_transitions(self):
        spark = _through_to(SparkStatus.PLANNED)
        names = [type(e).__name__ for e in spark.pending_events]
        assert names == ["SparkCaptured", "SparkEnriched", "SparkSuggested", "SparkPlanned"]

    def test_clearing_events_returns_a_clean_spark(self):
        spark = _through_to(SparkStatus.PLANNED).with_events_cleared()
        assert spark.pending_events == ()
        assert spark.status is SparkStatus.PLANNED

    def test_the_spark_is_frozen(self):
        with pytest.raises(AttributeError):
            _capture().status = SparkStatus.ARCHIVED  # type: ignore[misc]

    def test_updated_at_advances_with_each_transition(self):
        spark = _through_to(SparkStatus.SUGGESTED)
        assert spark.updated_at > spark.created_at

    def test_every_event_declares_its_aggregate(self):
        for event in _through_to(SparkStatus.PLANNED).pending_events:
            assert event.aggregate_id == "spk-1"


class TestAgeAwareness:
    def test_a_spark_knows_whether_a_child_has_grown_into_it(self):
        spark = _enriched()
        assert spark.is_age_appropriate_for(5) is True
        assert spark.is_age_appropriate_for(2) is False

    def test_a_spark_without_an_age_range_suits_any_age(self):
        spark = _capture()
        assert spark.age_range is None
        assert spark.is_age_appropriate_for(3) is True

    def test_days_since_capture_is_measured_from_the_moment_of_noticing(self):
        assert _enriched().days_since_capture(T0 + timedelta(days=243)) == 243
