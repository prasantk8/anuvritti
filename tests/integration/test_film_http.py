"""TASK-716 — the phone receives one truthful annual evidence shelf."""

from __future__ import annotations

from datetime import UTC, datetime

from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient


def test_compilation_is_the_childs_sources_in_capture_order(tmp_path):
    clock = FrozenClock(datetime(2026, 2, 1, 9, tzinfo=UTC))
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "film.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    box = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    client = PairedClient(create_app(settings, container=box))
    family = client.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    client.post(
        f"/v1/families/{family['id']}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    )

    recording_id = client.post(
        "/v1/media",
        files={
            "file": (
                "voice.m4a",
                b"\x00\x00\x00\x20ftypM4A " + b"a" * 80,
                "audio/m4a",
            )
        },
    ).json()["id"]
    client.post("/v1/voice", json={"media_id": recording_id, "duration_seconds": 3.2})
    clock.advance(days=1)
    spark = client.post(
        "/v1/sparks", json={"source": {"kind": "TEXT", "text": "the moon book"}}
    ).json()
    client.post(f"/v1/sparks/{spark['id']}/why", json={"text": "he points at every moon"})

    response = client.post("/v1/film/compile")
    assert response.status_code == 200
    film = response.json()
    assert film["child_name"] == "Aarav"
    assert film["year"] == 2026
    assert [item["kind"] for item in film["materials"]] == ["RECORDING", "SPARK"]
    assert film["materials"][1]["spark"]["why"]["text"] == "he points at every moon"
    assert film["rendered_media_id"] is None
    assert not set(film) & {"count", "scenes", "minutes", "percentage", "progress"}
    box.close()
