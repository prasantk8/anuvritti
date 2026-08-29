"""TASK-601..606 - voice, end to end over the real HTTP stack.

Real SQLite, real encrypted media store, real use cases. Only the clock and the id
generator are frozen.

The shape being tested is two requests, not one: the bytes go to `POST /v1/media` and
`POST /v1/voice` says what they are. That looks like a wasted round trip against the
ten-second budget in PRD 11 and it is the opposite - the upload is the slow part, so it
starts the moment the button is released while the parent is still deciding whether to
type anything about it.
"""

from __future__ import annotations

import io
import wave
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient

T0 = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)


#: A short m4a-ish blob. The bytes are never decoded by anything under test; what matters
#: is that the media store treats them as audio.
def _clip(seconds: float = 0.25) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48_000)
        audio.writeframes(b"\x00\x00" * round(48_000 * seconds))
    return buffer.getvalue()


CLIP = _clip()


@pytest.fixture
def api(tmp_path):
    class Api:
        def __init__(self) -> None:
            self.clock = FrozenClock(T0)
            settings = load_settings(
                {
                    "ANUVRITTI_ENV": "test",
                    "ANUVRITTI_DB_PATH": str(tmp_path / "api.db"),
                    "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
                    "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
                }
            ).unwrap()
            self.container = build_container(
                settings, clock=self.clock, ids=SequentialIdGenerator("id")
            )
            self.client = PairedClient(create_app(settings, container=self.container))
            family = self.client.post(
                "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
            ).json()
            self.family_id = family["id"]
            self.papa_id = family["members"][0]["id"]

        def upload(self, content: bytes = CLIP, mime: str = "audio/wav") -> str:
            response = self.client.post("/v1/media", files={"file": ("note.m4a", content, mime)})
            assert response.status_code == 201, response.text
            return response.json()["id"]

        def keep(self, *, duration: float = 4.2, **overrides):
            body = {"media_id": self.upload(), "duration_seconds": duration}
            body.update(overrides)
            return self.client.post("/v1/voice", json=body)

    return Api()


class TestKeepingARecording:
    def test_a_recording_is_kept_and_described_by_its_own_media_id(self, api):
        response = api.keep()
        assert response.status_code == 201
        body = response.json()
        assert body["media_id"].startswith("id-")
        assert body["duration_seconds"] == 0.25
        assert body["recorded_at"] == T0.isoformat()

    def test_nothing_is_indexed_by_default_and_that_is_a_complete_answer(self, api):
        """The shipping configuration: no model installed, every recording kept."""
        assert api.keep().json()["transcript"] is None

    @pytest.mark.parametrize("claimed", [-1.0, 0.0, 0.3, 4.2, 190.0])
    def test_the_handsets_timer_never_decides_the_duration(self, api, claimed):
        kept = api.keep(duration=claimed)
        assert kept.status_code == 201
        assert kept.json()["duration_seconds"] == 0.25

    def test_a_photograph_is_not_a_voice_note(self, api):
        photo = api.client.post(
            "/v1/media", files={"file": ("f.jpg", b"\xff\xd8\xff\xe0" + b"face" * 40, "image/jpeg")}
        ).json()["id"]
        response = api.client.post("/v1/voice", json={"media_id": photo, "duration_seconds": 4.0})
        assert response.status_code == 415

    def test_an_unknown_media_id_is_a_404(self, api):
        response = api.client.post(
            "/v1/voice", json={"media_id": "id-nope", "duration_seconds": 4.0}
        )
        assert response.status_code == 404

    def test_keeping_is_replayable_so_a_lost_signal_costs_nothing(self, api):
        """The phone that held the button has already dropped the audio buffer."""
        media_id = api.upload()
        body = {"media_id": media_id, "duration_seconds": 4.2}
        first = api.client.post("/v1/voice", json=body, headers={"Idempotency-Key": "queue-1"})
        second = api.client.post("/v1/voice", json=body, headers={"Idempotency-Key": "queue-1"})
        assert first.status_code == second.status_code == 201
        assert first.json() == second.json()
        assert len(api.client.get("/v1/voice").json()["recordings"]) == 1


class TestWhatThePhoneHeard:
    """PRD 8.7 - a transcript the handset brought with it is still a machine's reading."""

    def test_it_is_kept_with_machine_provenance(self, api):
        transcript = api.keep(heard_text="he called the elevator an alligator").json()["transcript"]
        assert transcript["text"] == "he called the elevator an alligator"
        assert transcript["source"] == "AI"
        assert transcript["engine"] == "device-speech"

    def test_it_never_claims_certainty_however_sure_the_phone_says_it_is(self, api):
        transcript = api.keep(heard_text="perfectly clear", heard_confidence=1.0).json()[
            "transcript"
        ]
        assert transcript["confidence"] < 1.0

    def test_an_unlabelled_reading_lands_below_low_so_it_renders_as_a_question(self, api):
        transcript = api.keep(heard_text="probably this").json()["transcript"]
        assert transcript["confidence"] < 0.5

    def test_a_blank_reading_is_simply_no_reading(self, api):
        assert api.keep(heard_text="   ").json()["transcript"] is None


class TestCorrectingWhatTheMachineMisheard:
    def test_a_parent_can_say_what_was_actually_said(self, api):
        media_id = api.keep(heard_text="he called the alligator an elevator").json()["media_id"]
        corrected = api.client.post(
            f"/v1/voice/{media_id}/transcript",
            json={"text": "he called the elevator an alligator"},
        )
        assert corrected.status_code == 200
        transcript = corrected.json()["transcript"]
        assert transcript["text"] == "he called the elevator an alligator"
        assert transcript["source"] == "HUMAN"
        assert transcript["confidence"] == 1.0
        assert transcript["engine"] == "hand"

    def test_the_audio_is_not_touched(self, api):
        media_id = api.keep(duration=4.2).json()["media_id"]
        api.client.post(f"/v1/voice/{media_id}/transcript", json={"text": "words"})
        after = api.client.get(f"/v1/voice/{media_id}").json()
        assert after["duration_seconds"] == 0.25
        assert api.client.get(f"/v1/media/{media_id}").content == CLIP

    def test_a_blank_correction_is_refused_rather_than_erasing_the_index(self, api):
        media_id = api.keep(heard_text="something").json()["media_id"]
        assert (
            api.client.post(f"/v1/voice/{media_id}/transcript", json={"text": "  "}).status_code
            == 422
        )

    def test_correcting_an_unknown_recording_is_a_404(self, api):
        assert (
            api.client.post("/v1/voice/id-nope/transcript", json={"text": "x"}).status_code == 404
        )


class TestThePapaVoiceVault:
    """PRD 21. A shelf, not an inbox."""

    def test_every_recording_is_there_newest_first(self, api):
        first = api.keep().json()["media_id"]
        api.clock.advance(days=1)
        second = api.keep().json()["media_id"]

        vault = api.client.get("/v1/voice").json()
        assert [r["media_id"] for r in vault["recordings"]] == [second, first]

    def test_it_carries_no_count_of_any_kind(self, api):
        api.keep()
        api.keep()
        vault = api.client.get("/v1/voice").json()
        assert set(vault) == {"recordings"}
        for forbidden in ("total", "count", "unheard", "new", "next", "cursor"):
            assert forbidden not in vault

    def test_an_unindexed_recording_is_not_hidden_from_the_shelf(self, api):
        """Being unsearchable is not being incomplete."""
        api.keep()
        recordings = api.client.get("/v1/voice").json()["recordings"]
        assert len(recordings) == 1
        assert recordings[0]["transcript"] is None

    def test_the_empty_vault_is_a_finished_state_rather_than_an_error(self, api):
        assert api.client.get("/v1/voice").json() == {"recordings": []}


class TestIsolation:
    def test_another_family_cannot_read_a_recording_by_guessing_its_id(self, api, tmp_path):
        media_id = api.keep().json()["media_id"]

        stranger = api.client.another_device()
        stranger.post("/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"})
        assert stranger.get(f"/v1/voice/{media_id}").status_code == 404
        assert stranger.get("/v1/voice").json() == {"recordings": []}

    def test_a_stranger_cannot_rewrite_what_a_parent_said(self, api):
        media_id = api.keep(heard_text="his own words").json()["media_id"]
        stranger = api.client.another_device()
        stranger.post("/v1/families", json={"name": "Theirs", "owner_display_name": "Someone"})

        assert (
            stranger.post(f"/v1/voice/{media_id}/transcript", json={"text": "not his"}).status_code
            == 404
        )
        assert (
            api.client.get(f"/v1/voice/{media_id}").json()["transcript"]["text"] == "his own words"
        )

    def test_the_vault_needs_a_token_at_all(self, api):
        assert api.client.as_unpaired().get("/v1/voice").status_code == 401


class TestVoiceRidesWithTheThingItExplains:
    """TASK-602 - the recording renders above the text, and the text never replaces it."""

    def test_a_why_carries_its_recording_and_not_only_the_media_id(self, api):
        spark = api.client.post(
            "/v1/sparks", json={"source": {"kind": "TEXT", "text": "balance bike"}}
        ).json()
        media_id = api.keep(heard_text="I never had one of these growing up").json()["media_id"]

        api.client.post(f"/v1/sparks/{spark['id']}/why", json={"voice_media_id": media_id})
        why = api.client.get(f"/v1/sparks/{spark['id']}").json()["why"]

        assert why["voice_media_id"] == media_id
        assert why["voice"]["duration_seconds"] == 0.25
        assert why["voice"]["transcript"]["text"] == "I never had one of these growing up"

    def test_a_why_with_only_words_has_no_recording_and_says_so_plainly(self, api):
        spark = api.client.post(
            "/v1/sparks", json={"source": {"kind": "TEXT", "text": "balance bike"}}
        ).json()
        api.client.post(f"/v1/sparks/{spark['id']}/why", json={"text": "he would love it"})
        why = api.client.get(f"/v1/sparks/{spark['id']}").json()["why"]
        assert why["text"] == "he would love it"
        assert why["voice"] is None

    def test_a_little_thing_carries_its_recording(self, api):
        media_id = api.keep(heard_text="we both laughed for no reason").json()["media_id"]
        thing = api.client.post("/v1/little-things", json={"audio_media_id": media_id}).json()
        assert thing["voice"]["media_id"] == media_id
        assert thing["voice"]["transcript"]["text"] == "we both laughed for no reason"
        assert thing["text"] is None

    def test_a_recording_without_a_note_row_still_plays(self, api):
        """A V0 archive has audio and no `voice_note` rows at all.

        The screen falls back to a player with no waveform and no transcript. That is a
        worse screen and a true one, and it must not be a 404.
        """
        orphan = api.upload()
        thing = api.client.post("/v1/little-things", json={"audio_media_id": orphan}).json()
        assert thing["audio_media_id"] == orphan
        assert thing["voice"] is None
        assert api.client.get(f"/v1/media/{orphan}").status_code == 200


class TestSpeakingIsCapturing:
    """TASK-604 over the wire - a spoken Spark is understood, not merely stored."""

    def test_a_transcript_earns_an_intent_the_way_a_caption_would(self, api):
        media_id = api.keep(heard_text="I want to do this with him one weekend").json()["media_id"]
        spark = api.client.post(
            "/v1/sparks",
            json={
                "source": {
                    "kind": "VOICE",
                    "media_id": media_id,
                    "text": "I want to do this with him one weekend",
                }
            },
        ).json()
        assert spark["intent"]["value"] == "DO"
        assert spark["intent"]["source"] == "AI"
        assert spark["intent"]["confidence"] < 1.0

    def test_the_parent_can_overrule_the_machine_and_it_sticks(self, api):
        media_id = api.upload()
        spark = api.client.post(
            "/v1/sparks",
            json={"source": {"kind": "VOICE", "media_id": media_id, "text": "buy this"}},
        ).json()
        corrected = api.client.post(
            f"/v1/sparks/{spark['id']}/override", json={"field": "intent", "value": "TEACH"}
        ).json()
        assert corrected["intent"] == {
            "value": "TEACH",
            "source": "HUMAN",
            "confidence": 1.0,
            "human_override": True,
        }


class TestTheFamilyKeepsIt:
    def test_the_export_carries_every_recording_with_its_provenance(self, api):
        api.keep(heard_text="a machine heard this")
        by_hand = api.keep().json()["media_id"]
        api.client.post(f"/v1/voice/{by_hand}/transcript", json={"text": "a person wrote this"})

        archive = api.client.get(f"/v1/families/{api.family_id}/export").json()
        readings = {
            r["transcript"]["text"]: r["transcript"]["source"]
            for r in archive["recordings"]
            if r["transcript"]
        }
        assert readings == {"a machine heard this": "AI", "a person wrote this": "HUMAN"}

    def test_the_export_measures_rather_than_describes_the_length(self, api):
        """TASK-707 will cut a film against this number, so it has to be a number."""
        api.keep(duration=4.2)
        archive = api.client.get(f"/v1/families/{api.family_id}/export").json()
        assert archive["recordings"][0]["duration_seconds"] == 0.25

    def test_deleting_the_family_takes_the_recordings_with_it(self, api):
        api.keep()
        counts = api.client.delete(f"/v1/families/{api.family_id}").json()
        assert counts["recordings"] == 1
        assert api.container.connection.execute("SELECT * FROM voice_note").fetchall() == []
