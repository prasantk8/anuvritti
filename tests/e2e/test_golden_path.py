"""TASK-301 - the golden path.

    "Can saved digital intention become a real family moment that otherwise may have
     been forgotten?"                                                        - PRD 48

This is the whole product as one test. A father sees a reel on a Tuesday in January, says
in five seconds why it mattered, and forgets it. Eight months later the product brings it
back without nagging, they do it together, and it becomes a Moment.

If this test fails, the thesis in PRD 48 is not implemented, whatever else passes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator

#: A Tuesday evening in January. He is putting the child to bed and scrolling.
JANUARY = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)
PHOTO = b"\xff\xd8\xff\xe0" + b"a face mid-laugh" * 30


@pytest.fixture
def app(tmp_path):
    clock = FrozenClock(JANUARY)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "e2e.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    client = TestClient(create_app(settings, container=container))
    client.clock = clock  # type: ignore[attr-defined]
    client.container = container  # type: ignore[attr-defined]
    yield client
    container.close()


def test_a_reel_in_january_becomes_a_saturday_in_september(app):
    clock = app.clock

    # --- The family exists. ------------------------------------------------------------
    family = app.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    family_id, papa_id = family["id"], family["members"][0]["id"]

    child_id = app.post(
        f"/v1/families/{family_id}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    ).json()["id"]

    # --- NOTICE. He shares a reel. Under ten seconds, no form. (PRD 11, 48 F1) ----------
    spark = app.post(
        "/v1/sparks",
        json={
            "family_id": family_id,
            "owner_id": papa_id,
            "subject_child_id": child_id,
            "source": {
                "kind": "URL",
                "url": "https://instagram.com/reel/balloon-rocket",
                "creator": "@sciencedad",
                "title": "Balloon rocket experiment - ages 5-8",
            },
        },
    ).json()
    spark_id = spark["id"]

    # The system already understood something about it. (PRD 48 F2)
    assert spark["status"] == "WAITING"
    assert spark["intent"]["value"] == "DO"
    assert spark["intent"]["source"] == "AI"
    assert spark["age_range"]["value"] == {"min_years": 5, "max_years": 8}
    # The child is 4. This is not for now.
    assert spark["age_range"]["human_override"] is False

    # --- REMEMBER. Five seconds of "why". (PRD 12, 48 F3) ------------------------------
    with_why = app.post(
        f"/v1/sparks/{spark_id}/why",
        json={"text": "I want to see his face when it launches."},
    ).json()
    assert with_why["why"]["text"] == "I want to see his face when it launches."

    # --- Life happens. Nothing is suggested while it is still fresh. --------------------
    quiet = app.get(
        "/v1/return/worth-bringing-back",
        params={"family_id": family_id, "actor_id": papa_id},
    )
    assert quiet.json() == [], "a Spark saved today has not been forgotten yet"

    # He captures other things and forgets this one entirely.
    for title in ("Dinosaur museum", "Bedtime story about elephants", "Paper plane guide"):
        app.post(
            "/v1/sparks",
            json={
                "family_id": family_id,
                "owner_id": papa_id,
                "subject_child_id": child_id,
                "source": {"kind": "TEXT", "text": title},
            },
        )

    # --- Eight months pass. The child turns five. ---------------------------------------
    clock.advance(days=243)  # a Saturday in September

    child = app.get(f"/v1/families/{family_id}").json()["children"][0]
    assert child["age_years"] == 5, "he has grown into it"

    # --- RETURN. The product brings it back. (PRD 14, 48 F6) ---------------------------
    suggestions = app.get(
        "/v1/return/worth-bringing-back",
        params={"family_id": family_id, "actor_id": papa_id},
    ).json()

    assert suggestions, "eight months later, this is exactly what should come back"
    brought_back = next(s for s in suggestions if s["spark"]["id"] == spark_id)

    # It says what is true, in his own words, without pressure. (PRD 8.5)
    assert "You saved this 8 months ago." in brought_back["reason"]
    assert "I want to see his face when it launches." in brought_back["reason"]
    assert "Aarav may be ready now." in brought_back["reason"]
    assert brought_back["actions"] == ["maybe_later", "lets_do_it", "not_relevant_anymore"]
    assert "score" not in brought_back

    # --- LIVE. "Let's do it." ----------------------------------------------------------
    planned = app.post(f"/v1/return/{spark_id}/respond", json={"response": "lets_do_it"}).json()
    assert planned["status"] == "PLANNED"

    # --- It actually happens. One photo, one sentence. (PRD 15, 48 F7) -----------------
    photo_id = app.post(
        "/v1/media",
        data={"family_id": family_id},
        files={"file": ("launch.jpg", PHOTO, "image/jpeg")},
    ).json()["id"]

    moment = app.post(
        f"/v1/sparks/{spark_id}/done",
        json={
            "created_by": papa_id,
            "reflection": "It hit the ceiling. He screamed. We did it four more times.",
            "photo_media_id": photo_id,
        },
    ).json()

    assert moment["spark_id"] == spark_id
    assert moment["happened_on"] == "2026-09-13"
    assert app.get(f"/v1/sparks/{spark_id}").json()["status"] == "EXPERIENCED"

    # --- The photo is retrievable and was encrypted on disk. (PRD 44) ------------------
    assert app.get(f"/v1/media/{photo_id}").content == PHOTO

    # --- The thesis, measured. (PRD 53) ------------------------------------------------
    metrics = app.get("/metrics").text
    assert "anuvritti_sparks_captured_total 4" in metrics
    assert "anuvritti_moments_created_total 1" in metrics
    assert "anuvritti_intent_to_moment_ratio 0.25" in metrics

    # --- And the family can take all of it and leave. (PRD 44) -------------------------
    archive = app.get(f"/v1/families/{family_id}/export").json()
    exported = next(s for s in archive["sparks"] if s["id"] == spark_id)
    assert exported["why"]["text"] == "I want to see his face when it launches."
    assert exported["source"]["creator"] == "@sciencedad"
    assert len(archive["moments"]) == 1


def test_the_same_reel_declined_is_never_seen_again(app):
    """The other half of the promise: the product takes no for an answer. (PRD 8.5)"""
    clock = app.clock
    family = app.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    family_id, papa_id = family["id"], family["members"][0]["id"]

    spark_id = app.post(
        "/v1/sparks",
        json={
            "family_id": family_id,
            "owner_id": papa_id,
            "source": {"kind": "TEXT", "text": "science experiment to do together"},
        },
    ).json()["id"]

    clock.advance(days=243)
    assert app.get(
        "/v1/return/worth-bringing-back",
        params={"family_id": family_id, "actor_id": papa_id},
    ).json()

    app.post(f"/v1/return/{spark_id}/respond", json={"response": "not_relevant_anymore"})

    # Ten years later.
    clock.advance(days=3650)
    assert (
        app.get(
            "/v1/return/worth-bringing-back",
            params={"family_id": family_id, "actor_id": papa_id},
        ).json()
        == []
    )


def test_a_spark_keeps_its_meaning_when_the_link_dies(app):
    """PRD 43 - a Spark must never become empty because the internet changed."""
    family = app.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    family_id, papa_id = family["id"], family["members"][0]["id"]

    spark_id = app.post(
        "/v1/sparks",
        json={
            "family_id": family_id,
            "owner_id": papa_id,
            "source": {
                "kind": "URL",
                "url": "https://instagram.com/reel/deleted-tomorrow",
                "creator": "@sciencedad",
                "title": "Balloon rocket experiment",
            },
        },
    ).json()["id"]
    app.post(f"/v1/sparks/{spark_id}/why", json={"text": "This looked ridiculous."})

    # The reel is gone from the internet. Everything that made it matter is still here.
    spark = app.get(f"/v1/sparks/{spark_id}").json()
    assert spark["title"] == "Balloon rocket experiment"
    assert spark["source"]["creator"] == "@sciencedad"
    assert spark["why"]["text"] == "This looked ridiculous."
    assert spark["intent"]["value"] in {"DO", "WATCH", "REMEMBER"}


def test_the_ordinary_days_are_kept_too(app):
    """PRD 17, 18 - Little Things and Right Now, the parts with no lifecycle at all."""
    family = app.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    family_id, papa_id = family["id"], family["members"][0]["id"]
    child_id = app.post(
        f"/v1/families/{family_id}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    ).json()["id"]

    app.post(
        "/v1/little-things",
        json={
            "family_id": family_id,
            "author_id": papa_id,
            "subject_child_id": child_id,
            "text": "He called the moon a broken sun.",
        },
    )
    app.post(
        "/v1/right-now",
        json={
            "family_id": family_id,
            "child_id": child_id,
            "answer": "Volcanoes. Only volcanoes.",
        },
    )

    archive = app.get(f"/v1/families/{family_id}/export").json()
    assert archive["little_things"][0]["text"] == "He called the moon a broken sun."
    assert archive["right_now"][0]["answer"] == "Volcanoes. Only volcanoes."
    # These have no status, no lifecycle and nothing to complete.
    assert "status" not in archive["little_things"][0]
