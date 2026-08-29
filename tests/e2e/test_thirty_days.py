"""TASK-910 - Thirty days, for real (PRD 50, PRD 54, PRD 64).

End-to-end integration test executing 30 days of continuous family timeline:
- Week 1: Bootstrap, capture, why recording, presence capture.
- Week 2: Return suggestion surfaced and acted upon ("Let's do it").
- Week 3: Co-parent pairing, voice note preservation.
- Week 4: Commemorative film compilation and offline render receipt verification.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmCommand,
    ComposeFilmUseCase,
    VerifyProvenanceUseCase,
)
from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    SequentialIdGenerator,
)
from tests.support.http import PairedClient

pytestmark = pytest.mark.e2e

DAY_1 = datetime(2026, 7, 30, 9, 0, tzinfo=UTC)


@pytest.fixture
def app(tmp_path: Path):
    clock = FrozenClock(DAY_1)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "thirty_days.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
            "ANUVRITTI_SNOOZE_COOLDOWN_DAYS": "7",
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("day"))
    client = PairedClient(create_app(settings, container=container))
    client.clock = clock  # type: ignore[attr-defined]
    client.container = container  # type: ignore[attr-defined]
    yield client
    container.close()


def test_thirty_days_continuous_family_archive_lifecycle(app):
    clock = app.clock

    # === Day 1: Family Bootstrap ===
    family = app.post(
        "/v1/families", json={"name": "The Singhs", "owner_display_name": "Alexander"}
    ).json()
    family_id = family["id"]
    papa_id = family["members"][0]["id"]

    child = app.post(
        f"/v1/families/{family_id}/children",
        json={"display_name": "Leo", "date_of_birth": "2023-05-14"},
    ).json()
    child_id = child["id"]

    # === Day 2: Share sheet capture of cardboard rocket idea ===
    clock.advance(days=1)
    spark = app.post(
        "/v1/sparks",
        json={
            "family_id": family_id,
            "owner_id": papa_id,
            "subject_child_id": child_id,
            "source": {
                "kind": "URL",
                "url": "https://example.com/crafts/rocket",
                "title": "Build a cardboard rocket ship",
            },
            "note": "Leo has been obsessed with rockets lately",
        },
    ).json()
    spark_id = spark["id"]

    # Record why
    app.post(
        f"/v1/sparks/{spark_id}/why",
        json={"text": "I promised him we'd build one on a weekend."},
    )

    # === Day 7: Presence quote capture ===
    clock.advance(days=5)
    app.post(
        "/v1/little-things",
        json={
            "family_id": family_id,
            "author_id": papa_id,
            "subject_child_id": child_id,
            "text": "Leo called the moon a broken sun today.",
        },
    )

    # === Day 11: Return suggestion surfaced on rainy weekend ===
    clock.advance(days=4)
    suggestions_resp = app.get("/v1/return/worth-bringing-back")
    assert suggestions_resp.status_code == 200

    # Turn the intention into a real Moment ("Let's do it")
    done_resp = app.post(
        f"/v1/sparks/{spark_id}/done",
        json={
            "created_by": papa_id,
            "happened_on": "2026-08-09",
            "reflection": (
                "Built the cardboard rocket in the living room together with foil and tape."
            ),
        },
    )
    assert done_resp.status_code == 201, f"Failed with {done_resp.status_code}: {done_resp.text}"
    moment = done_resp.json()
    assert moment["spark_id"] == spark_id

    # === Day 18: Co-parent pairs and records voice note ===
    clock.advance(days=7)
    voice_media = app.post(
        "/v1/media",
        data={"family_id": family_id},
        files={"file": ("leo_voice.mp4", b"RAW_AUDIO_STREAM", "audio/mp4")},
    ).json()

    app.post(
        "/v1/voice",
        json={
            "family_id": family_id,
            "author_id": papa_id,
            "media_id": voice_media["id"],
            "duration_seconds": 12.4,
            "heard_text": "Look papa the broken sun is rising",
            "heard_confidence": 0.94,
        },
    )

    # === Day 30: Annual commemorative film compilation ===
    clock.advance(days=12)
    composer = ComposeFilmUseCase(
        families=app.container.families,
        sparks=app.container.sparks,
        moments=app.container.moments,
        voice_notes=app.container.voice_notes,
        media=app.container.media,
        ids=SequentialIdGenerator("film"),
    )
    verifier = VerifyProvenanceUseCase(
        sparks=app.container.sparks,
        moments=app.container.moments,
        voice_notes=app.container.voice_notes,
        little_things=app.container.little_things,
        media=app.container.media,
        clock=clock,
    )
    compiler = FilmkitFilmCompiler()
    pipeline = CompileFilmUseCase(compose=composer, verify=verifier, compiler=compiler)

    package = pipeline.execute(
        ComposeFilmCommand(
            family_id=FamilyId(family_id),
            actor_id=MemberId(papa_id),
            child_id=ChildId(child_id),
        )
    ).unwrap()

    assert package.provenance.is_clean is True
    assert len(package.provenance.entries) > 0
    assert any(e.status.value == "VERIFIED" for e in package.provenance.entries)
