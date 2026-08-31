"""TASK-804 - Email Ingest integration tests (PRD 27, PRD 11)."""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.capture import CaptureSparkUseCase
from anuvritti.interfaces.ingest.email import EmailIngestHandler
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.fakes import (
    CHILD,
    FAMILY,
    PAPA,
    InMemoryFamilyRepository,
    InMemoryMediaStore,
    InMemorySparkRepository,
    NullUnitOfWork,
    RecordingEventPublisher,
    build_family,
)

NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def harness():
    families = InMemoryFamilyRepository()
    families.save(build_family()).unwrap()
    sparks = InMemorySparkRepository()
    media = InMemoryMediaStore()
    events = RecordingEventPublisher()
    clock = FrozenClock(NOW)
    ids = SequentialIdGenerator("spk")
    uow = NullUnitOfWork()

    capture_use_case = CaptureSparkUseCase(
        families=families,
        sparks=sparks,
        intent_engine=HeuristicIntentEngine(),
        events=events,
        clock=clock,
        ids=ids,
        uow=uow,
    )

    handler = EmailIngestHandler(
        capture_spark=capture_use_case,
        media_store=media,
    )

    return type(
        "Harness",
        (),
        {
            "families": families,
            "sparks": sparks,
            "media": media,
            "events": events,
            "handler": handler,
        },
    )()


class TestEmailIngest:
    def test_ingests_plain_text_email_as_spark(self, harness):
        msg = EmailMessage()
        msg["Subject"] = "Stories of when your father was little"
        msg["From"] = "dadi@example.com"
        msg.set_content("Remember when he tried to climb the mango tree in Jaipur?")

        spark = harness.handler.process_raw_email(
            msg.as_bytes(),
            family_id=FAMILY,
            author_id=PAPA,
            child_id=CHILD,
        ).unwrap()

        assert spark.title == "Stories of when your father was little"
        assert "mango tree" in (spark.note or "")
        assert spark.subject_child_id == CHILD
        assert len(harness.sparks.list_for_family(FAMILY).unwrap()) == 1

    def test_ingests_audio_attachment_as_voice_why(self, harness):
        msg = EmailMessage()
        msg["Subject"] = "Singing our old lullaby"
        msg["From"] = "nani@example.com"
        msg.set_content("A quick song for tonight.")
        msg.add_attachment(
            b"FAKE_AUDIO_BYTES_FOR_TESTING",
            maintype="audio",
            subtype="m4a",
            filename="lullaby.m4a",
        )

        spark = harness.handler.process_raw_email(
            msg.as_bytes(),
            family_id=FAMILY,
            author_id=PAPA,
            child_id=CHILD,
        ).unwrap()

        assert spark.title == "Singing our old lullaby"
        assert spark.why is not None
        assert spark.why.voice_media_id is not None
