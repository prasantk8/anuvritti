"""TASK-204 - the Moment.

PRD 15: "No journaling burden." Every attachment is optional and *nothing* is a valid
answer to "did this happen?". A Moment that demands effort is a Moment that never exists.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from anuvritti.domain.events import MomentCreated
from anuvritti.domain.moment import Moment
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MemberId, MomentId, SparkId

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
LATER = T0 + timedelta(days=243)


def _moment(**kwargs) -> Moment:
    defaults = {
        "moment_id": MomentId("mom-1"),
        "family_id": FamilyId("fam-1"),
        "spark_id": SparkId("spk-1"),
        "created_by": MemberId("mem-papa"),
        "spark_captured_at": T0,
        "at": LATER,
    }
    return Moment.create(**{**defaults, **kwargs}).unwrap()


class TestCreation:
    def test_a_moment_can_be_created_with_nothing_attached(self):
        """PRD 15 - 'nothing' is on the list of valid answers."""
        moment = _moment()
        assert moment.reflection is None
        assert moment.photo_media_id is None
        assert moment.audio_media_id is None

    def test_happened_on_defaults_to_the_day_it_was_marked(self):
        assert _moment().happened_on == LATER.date()

    def test_happened_on_can_be_backdated(self):
        moment = _moment(happened_on=date(2026, 8, 1))
        assert moment.happened_on == date(2026, 8, 1)

    def test_a_future_date_is_rejected(self):
        """A Moment is something that happened, not something planned."""
        err = Moment.create(
            moment_id=MomentId("mom-1"),
            family_id=FamilyId("fam-1"),
            spark_id=SparkId("spk-1"),
            created_by=MemberId("mem-papa"),
            spark_captured_at=T0,
            at=LATER,
            happened_on=LATER.date() + timedelta(days=2),
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_a_date_before_the_spark_was_captured_is_rejected(self):
        err = Moment.create(
            moment_id=MomentId("mom-1"),
            family_id=FamilyId("fam-1"),
            spark_id=SparkId("spk-1"),
            created_by=MemberId("mem-papa"),
            spark_captured_at=T0,
            at=LATER,
            happened_on=date(2025, 1, 1),
        ).unwrap_err()
        assert err.code is ErrorCode.VALIDATION_FAILED

    def test_one_sentence_is_enough(self):
        assert _moment(reflection="He laughed so hard he fell over.").reflection is not None

    def test_a_blank_reflection_is_treated_as_no_reflection(self):
        assert _moment(reflection="   ").reflection is None

    def test_a_photo_alone_is_enough(self):
        assert _moment(photo_media_id="med-photo").has_evidence is True

    def test_audio_alone_is_enough(self):
        assert _moment(audio_media_id="med-audio").has_evidence is True

    def test_a_moment_with_nothing_attached_still_counts(self):
        """The conversion metric counts the experience, not the documentation."""
        assert _moment().has_evidence is False


class TestEventsAndMetrics:
    def test_creation_emits_moment_created(self):
        events = _moment().pending_events
        assert isinstance(events[0], MomentCreated)

    def test_the_event_carries_the_days_from_capture(self):
        """PRD 53 - this is how Intent -> Moment conversion becomes measurable."""
        event = _moment().pending_events[0]
        assert isinstance(event, MomentCreated)
        assert event.days_from_capture == 243

    def test_the_event_records_what_was_attached_but_not_its_content(self):
        event = _moment(reflection="something private", photo_media_id="m1").pending_events[0]
        assert isinstance(event, MomentCreated)
        assert event.has_reflection is True
        assert event.has_photo is True
        assert "private" not in str(event.payload())

    def test_days_from_capture_is_never_negative(self):
        moment = _moment(happened_on=T0.date())
        event = moment.pending_events[0]
        assert isinstance(event, MomentCreated)
        assert event.days_from_capture >= 0


class TestImmutability:
    def test_a_moment_is_frozen(self):
        with pytest.raises(AttributeError):
            _moment().reflection = "edited"  # type: ignore[misc]

    def test_clearing_events_preserves_the_moment(self):
        moment = _moment().with_events_cleared()
        assert moment.pending_events == ()
        assert moment.id == MomentId("mom-1")
