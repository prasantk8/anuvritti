"""TASK-1102 - Privacy budget for logs (PRD 44, PRD 46).

A privacy budget for logs: no content, no transcript, no filename and no child's
name can reach a log line, asserted by reading the emitted stream back.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient

pytestmark = pytest.mark.constitution


@pytest.fixture
def client(tmp_path: Path):
    clock = FrozenClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "app.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
            "ANUVRITTI_LOG_LEVEL": "INFO",
        }
    ).unwrap()

    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("log_test"))
    test_client = PairedClient(create_app(settings, container=container))
    test_client.clock = clock  # type: ignore[attr-defined]
    test_client.container = container  # type: ignore[attr-defined]
    yield test_client
    container.close()


def test_log_stream_never_contains_child_name_or_family_content(client, capsys):
    # 1. Create family and child
    family = client.post(
        "/v1/families",
        json={"name": "The Singer Family", "owner_display_name": "Alexander"},
    ).json()

    child = client.post(
        f"/v1/families/{family['id']}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    ).json()

    # 2. Capture a spark with sensitive text and why
    spark = client.post(
        "/v1/sparks",
        json={
            "family_id": family["id"],
            "owner_id": family["members"][0]["id"],
            "subject_child_id": child["id"],
            "source": {
                "kind": "TEXT",
                "text": "Private secret bedtime story about a magical blue dragon",
            },
            "note": "Aarav loves magical blue dragons in the bedroom",
        },
    ).json()

    client.post(
        f"/v1/sparks/{spark['id']}/why",
        json={"text": "Because he couldn't sleep after thunderstorm"},
    )

    # 3. Capture little thing
    client.post(
        "/v1/little-things",
        json={
            "family_id": family["id"],
            "author_id": family["members"][0]["id"],
            "subject_child_id": child["id"],
            "text": "He called the moon a broken sun in the afternoon.",
        },
    )

    # 4. Read captured stream
    out = capsys.readouterr().out
    lines = [line.strip() for line in out.splitlines() if line.strip()]

    # Every log line must parse as valid JSON
    for line in lines:
        payload = json.loads(line)
        assert "timestamp" in payload
        assert "level" in payload
        assert "message" in payload

    # Assert zero private content in log output
    assert "Aarav" not in out
    assert "Alexander" not in out
    assert "The Singer Family" not in out
    assert "magical blue dragon" not in out
    assert "broken sun" not in out
    assert "thunderstorm" not in out
    assert "bedroom" not in out


def test_log_stream_never_contains_voice_transcript(client, capsys):
    family = client.post(
        "/v1/families",
        json={"name": "Voice Family", "owner_display_name": "Papa"},
    ).json()

    media_resp = client.post(
        "/v1/media",
        data={"family_id": family["id"]},
        files={"file": ("secret_voice.mp4", b"AUDIO_RAW_BYTES", "audio/mp4")},
    ).json()

    client.post(
        "/v1/voice",
        json={
            "family_id": family["id"],
            "author_id": family["members"][0]["id"],
            "media_id": media_resp["id"],
            "duration_seconds": 4.5,
            "heard_text": "I will always love you my sweet child",
            "heard_confidence": 0.95,
        },
    )

    out = capsys.readouterr().out
    assert "I will always love you" not in out
    assert "sweet child" not in out
    assert "secret_voice.mp4" not in out


def test_log_stream_never_contains_auth_tokens_or_keys(client, capsys):
    client.post(
        "/v1/families",
        json={"name": "Auth Family", "owner_display_name": "Papa"},
    )
    token = client.device_token
    assert token is not None

    client.get("/v1/devices")

    out = capsys.readouterr().out
    assert token not in out
    assert "Bearer" not in out
