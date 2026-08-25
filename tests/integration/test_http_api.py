"""TASK-216 - the HTTP interface against docs/contracts/openapi.yaml.

Runs the real stack: real SQLite, real media store, real use cases. Only the clock and
the id generator are frozen, so a test can watch eight months pass.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from anuvritti.config.settings import Environment, Settings, load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
PHOTO = b"\xff\xd8\xff\xe0" + b"his face" * 40


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
                    "ANUVRITTI_SUGGESTION_THRESHOLD": "0.3",
                }
            ).unwrap()
            self.container = build_container(
                settings, clock=self.clock, ids=SequentialIdGenerator("id")
            )
            self.client = TestClient(create_app(settings, container=self.container))
            self._bootstrap()

        def _bootstrap(self) -> None:
            family = self.client.post(
                "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
            ).json()
            self.family_id = family["id"]
            self.papa_id = family["members"][0]["id"]
            self.child_id = self.client.post(
                f"/v1/families/{self.family_id}/children",
                json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
            ).json()["id"]

        def capture(self, **overrides):
            body = {
                "family_id": self.family_id,
                "owner_id": self.papa_id,
                "subject_child_id": self.child_id,
                "source": {
                    "kind": "URL",
                    "url": "https://instagram.com/reel/abc",
                    "creator": "@sciencedad",
                    "title": "Balloon rocket experiment for ages 5-8",
                },
            }
            body.update(overrides)
            return self.client.post("/v1/sparks", json=body)

    api = Api()
    yield api
    api.container.close()


class TestBootstrap:
    def test_a_family_can_be_created(self, api):
        response = api.client.post(
            "/v1/families", json={"name": "Another", "owner_display_name": "Mum"}
        )
        assert response.status_code == 201
        assert response.json()["members"][0]["role"] == "PARENT"

    def test_a_child_is_created_with_a_computed_age(self, api):
        child = api.client.get(f"/v1/families/{api.family_id}").json()["children"][0]
        assert child["display_name"] == "Aarav"
        assert child["age_years"] == 4

    def test_a_child_cannot_be_born_in_the_future(self, api):
        response = api.client.post(
            f"/v1/families/{api.family_id}/children",
            json={"display_name": "Unborn", "date_of_birth": "2030-01-01"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"

    def test_an_unknown_family_is_a_404_with_a_stable_code(self, api):
        response = api.client.get("/v1/families/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FAMILY_NOT_FOUND"


class TestCapture:
    def test_a_share_returns_a_saved_spark(self, api):
        response = api.capture()
        assert response.status_code == 201
        assert response.json()["status"] == "WAITING"

    def test_the_response_always_carries_ai_provenance(self, api):
        """PRD 13, 42 - provenance is not an optional expansion."""
        intent = api.capture().json()["intent"]
        assert set(intent) == {"value", "source", "confidence", "human_override"}
        assert intent["source"] == "AI"

    def test_the_inferred_intent_is_always_one_of_the_six(self, api):
        assert api.capture().json()["intent"]["value"] in {
            "DO",
            "BUY",
            "WATCH",
            "READ",
            "TEACH",
            "REMEMBER",
        }

    def test_a_text_capture_needs_no_url(self, api):
        response = api.capture(source={"kind": "TEXT", "text": "teach him to whistle"})
        assert response.status_code == 201

    def test_a_url_capture_without_a_url_is_rejected_clearly(self, api):
        response = api.capture(source={"kind": "URL"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CAPTURE_SOURCE_INVALID"

    def test_a_javascript_url_is_refused(self, api):
        response = api.capture(source={"kind": "URL", "url": "javascript:alert(1)"})
        assert response.status_code == 422

    def test_an_unknown_field_is_rejected_rather_than_silently_ignored(self, api):
        """A typo in a client must not become a silently discarded wish about a child."""
        response = api.capture(mood="hopeful")
        assert response.status_code == 422

    def test_capturing_for_an_unknown_child_is_a_404(self, api):
        response = api.capture(subject_child_id="ghost")
        assert response.json()["error"]["code"] == "CHILD_NOT_FOUND"

    def test_a_captured_spark_can_be_read_back(self, api):
        spark_id = api.capture().json()["id"]
        assert api.client.get(f"/v1/sparks/{spark_id}").json()["id"] == spark_id

    def test_source_context_is_returned_so_the_client_survives_link_rot(self, api):
        """PRD 43."""
        source = api.capture().json()["source"]
        assert source["creator"] == "@sciencedad"


class TestWhyAndOverride:
    def test_a_why_can_be_recorded(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/sparks/{spark_id}/why", json={"text": "I never had one growing up"}
        )
        assert response.status_code == 200
        assert response.json()["why"]["text"] == "I never had one growing up"

    def test_an_empty_why_is_rejected(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(f"/v1/sparks/{spark_id}/why", json={})
        assert response.status_code == 422

    def test_a_parent_can_correct_the_intent(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/sparks/{spark_id}/override", json={"field": "intent", "value": "BUY"}
        )
        assert response.json()["intent"]["value"] == "BUY"
        assert response.json()["intent"]["human_override"] is True

    def test_a_v1_only_intent_is_refused_at_the_boundary(self, api):
        """PRD 48 F4 - the six are a product decision, enforced at the edge."""
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/sparks/{spark_id}/override", json={"field": "intent", "value": "COOK"}
        )
        assert response.status_code == 422

    def test_the_age_range_can_be_corrected(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/sparks/{spark_id}/override",
            json={"field": "age_range", "value": {"min_years": 2, "max_years": 3}},
        )
        age_range = response.json()["age_range"]
        assert age_range["value"] == {"min_years": 2, "max_years": 3}
        assert age_range["human_override"] is True

    def test_a_malformed_age_range_is_rejected(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/sparks/{spark_id}/override",
            json={"field": "age_range", "value": {"min_years": 9, "max_years": 2}},
        )
        assert response.status_code == 422

    def test_an_unknown_field_cannot_be_overridden(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/sparks/{spark_id}/override", json={"field": "mood", "value": "happy"}
        )
        assert response.status_code == 422


class TestVault:
    def test_search_finds_a_spark_by_text(self, api):
        api.capture()
        response = api.client.get(
            "/v1/sparks",
            params={"family_id": api.family_id, "actor_id": api.papa_id, "q": "balloon"},
        )
        assert len(response.json()) == 1

    def test_search_filters_by_intent(self, api):
        api.capture()
        response = api.client.get(
            "/v1/sparks",
            params={"family_id": api.family_id, "actor_id": api.papa_id, "intent": "DO"},
        )
        assert all(s["intent"]["value"] == "DO" for s in response.json())

    def test_an_invalid_intent_filter_is_rejected(self, api):
        response = api.client.get(
            "/v1/sparks",
            params={"family_id": api.family_id, "actor_id": api.papa_id, "intent": "COOK"},
        )
        assert response.status_code == 422

    def test_the_limit_is_bounded_by_the_framework(self, api):
        response = api.client.get(
            "/v1/sparks",
            params={"family_id": api.family_id, "actor_id": api.papa_id, "limit": 9999},
        )
        assert response.status_code == 422

    def test_searching_as_a_stranger_is_refused(self, api):
        response = api.client.get(
            "/v1/sparks", params={"family_id": api.family_id, "actor_id": "stranger"}
        )
        assert response.json()["error"]["code"] == "MEMBER_NOT_FOUND"


class TestReturnEngine:
    def _ask(self, api):
        return api.client.get(
            "/v1/return/worth-bringing-back",
            params={"family_id": api.family_id, "actor_id": api.papa_id},
        )

    def test_nothing_is_suggested_the_day_it_was_saved(self, api):
        api.capture()
        assert self._ask(api).json() == []

    def test_something_saved_eight_months_ago_comes_back(self, api):
        api.capture()
        api.clock.advance(days=245)
        assert len(self._ask(api).json()) == 1

    def test_the_suggestion_reads_like_a_person(self, api):
        api.capture()
        api.clock.advance(days=245)
        assert "You saved this 8 months ago" in self._ask(api).json()[0]["reason"]

    def test_the_suggestion_offers_the_three_prd_actions(self, api):
        api.capture()
        api.clock.advance(days=245)
        assert self._ask(api).json()[0]["actions"] == [
            "maybe_later",
            "lets_do_it",
            "not_relevant_anymore",
        ]

    def test_the_score_is_never_shown_to_the_parent(self, api):
        """PRD 8.5 - a score about your own child is not something to display."""
        api.capture()
        api.clock.advance(days=245)
        payload = self._ask(api).json()[0]
        assert "score" not in payload
        assert "suggested_count" not in payload["spark"]

    def test_lets_do_it_plans_it(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=245)
        self._ask(api)
        response = api.client.post(
            f"/v1/return/{spark_id}/respond", json={"response": "lets_do_it"}
        )
        assert response.json()["status"] == "PLANNED"

    def test_maybe_later_buys_real_quiet(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=245)
        self._ask(api)
        api.client.post(f"/v1/return/{spark_id}/respond", json={"response": "maybe_later"})
        api.clock.advance(days=5)
        assert self._ask(api).json() == []

    def test_not_relevant_anymore_is_permanent(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=245)
        self._ask(api)
        api.client.post(f"/v1/return/{spark_id}/respond", json={"response": "not_relevant_anymore"})
        api.clock.advance(days=3650)
        assert self._ask(api).json() == []

    def test_responding_twice_to_an_archived_spark_is_a_clear_conflict(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=245)
        self._ask(api)
        api.client.post(f"/v1/return/{spark_id}/respond", json={"response": "not_relevant_anymore"})
        response = api.client.post(
            f"/v1/return/{spark_id}/respond", json={"response": "lets_do_it"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SPARK_ARCHIVED"

    def test_an_unknown_response_is_rejected(self, api):
        spark_id = api.capture().json()["id"]
        response = api.client.post(
            f"/v1/return/{spark_id}/respond", json={"response": "remind_me_tomorrow"}
        )
        assert response.status_code == 422


class TestMarkAsDone:
    def test_a_spark_becomes_a_moment_with_nothing_attached(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=243)
        response = api.client.post(f"/v1/sparks/{spark_id}/done", json={"created_by": api.papa_id})
        assert response.status_code == 201
        assert response.json()["spark_id"] == spark_id

    def test_a_sentence_can_be_attached(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=243)
        response = api.client.post(
            f"/v1/sparks/{spark_id}/done",
            json={"created_by": api.papa_id, "reflection": "He laughed until he fell over."},
        )
        assert response.json()["reflection"].startswith("He laughed")

    def test_the_same_spark_cannot_become_two_moments(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=243)
        api.client.post(f"/v1/sparks/{spark_id}/done", json={"created_by": api.papa_id})
        response = api.client.post(f"/v1/sparks/{spark_id}/done", json={"created_by": api.papa_id})
        assert response.status_code == 409

    def test_the_spark_is_marked_experienced(self, api):
        spark_id = api.capture().json()["id"]
        api.clock.advance(days=243)
        api.client.post(f"/v1/sparks/{spark_id}/done", json={"created_by": api.papa_id})
        assert api.client.get(f"/v1/sparks/{spark_id}").json()["status"] == "EXPERIENCED"


class TestPresence:
    def test_a_little_thing_can_be_captured(self, api):
        response = api.client.post(
            "/v1/little-things",
            json={
                "family_id": api.family_id,
                "author_id": api.papa_id,
                "text": "He called the moon a broken sun.",
            },
        )
        assert response.status_code == 201

    def test_a_little_thing_needs_words_or_a_voice_note(self, api):
        response = api.client.post(
            "/v1/little-things", json={"family_id": api.family_id, "author_id": api.papa_id}
        )
        assert response.status_code == 422

    def test_todays_right_now_prompt_is_a_question(self, api):
        assert api.client.get("/v1/right-now").json()["prompt"].endswith("?")

    def test_a_right_now_answer_is_captured(self, api):
        response = api.client.post(
            "/v1/right-now",
            json={
                "family_id": api.family_id,
                "child_id": api.child_id,
                "answer": "Volcanoes. Only volcanoes.",
            },
        )
        assert response.status_code == 201
        assert response.json()["prompt"].endswith("?")

    def test_an_empty_right_now_answer_is_rejected(self, api):
        response = api.client.post(
            "/v1/right-now",
            json={"family_id": api.family_id, "child_id": api.child_id, "answer": ""},
        )
        assert response.status_code == 422


class TestMedia:
    def test_a_photo_can_be_uploaded_and_downloaded(self, api):
        upload = api.client.post(
            "/v1/media",
            data={"family_id": api.family_id},
            files={"file": ("photo.jpg", PHOTO, "image/jpeg")},
        )
        assert upload.status_code == 201
        assert upload.json()["encrypted"] is True
        media_id = upload.json()["id"]
        assert api.client.get(f"/v1/media/{media_id}").content == PHOTO

    def test_an_unsupported_type_is_refused(self, api):
        response = api.client.post(
            "/v1/media",
            data={"family_id": api.family_id},
            files={"file": ("page.html", b"<script>", "text/html")},
        )
        assert response.status_code == 415

    def test_media_is_never_cached_by_an_intermediary(self, api):
        upload = api.client.post(
            "/v1/media",
            data={"family_id": api.family_id},
            files={"file": ("photo.jpg", PHOTO, "image/jpeg")},
        )
        response = api.client.get(f"/v1/media/{upload.json()['id']}")
        assert "no-store" in response.headers["cache-control"]

    def test_unknown_media_is_a_404(self, api):
        assert api.client.get("/v1/media/nope").status_code == 404


class TestFamilyRights:
    def test_export_returns_the_whole_archive(self, api):
        api.capture()
        response = api.client.get(f"/v1/families/{api.family_id}/export")
        assert response.status_code == 200
        assert len(response.json()["sparks"]) == 1

    def test_export_is_offered_as_a_download(self, api):
        response = api.client.get(f"/v1/families/{api.family_id}/export")
        assert "attachment" in response.headers["content-disposition"]

    def test_delete_removes_everything_and_reports_it(self, api):
        api.capture()
        response = api.client.delete(f"/v1/families/{api.family_id}")
        assert response.status_code == 200
        assert response.json()["sparks"] == 1
        assert api.client.get(f"/v1/families/{api.family_id}").status_code == 404

    def test_deleting_an_unknown_family_is_a_404(self, api):
        assert api.client.delete("/v1/families/nope").status_code == 404


class TestErrorContract:
    def test_every_error_uses_the_documented_envelope(self, api):
        for response in (
            api.client.get("/v1/families/nope"),
            api.client.get("/v1/sparks/nope"),
            api.capture(source={"kind": "URL"}),
        ):
            body = response.json()
            assert set(body) == {"error"}
            assert set(body["error"]) == {"code", "message", "details"}

    def test_codes_are_stable_strings_from_the_catalogue(self, api):
        import re
        from pathlib import Path

        contract = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "errors.md"
        documented = set(re.findall(r"^\| `([A-Z_]+)` \|", contract.read_text(), re.MULTILINE))
        code = api.client.get("/v1/sparks/nope").json()["error"]["code"]
        assert code in documented


class TestApiSurface:
    def test_docs_are_available_outside_production(self, api):
        assert api.client.get("/docs").status_code == 200

    def test_docs_are_disabled_in_production(self, tmp_path):
        settings = Settings(
            environment=Environment.PRODUCTION,
            db_path=tmp_path / "p.db",
            media_dir=tmp_path / "m",
            media_key=Fernet.generate_key().decode(),
            log_level="INFO",
            tls_required=True,
            expose_api_docs=False,
            max_media_bytes=1024,
            allowed_media_types=frozenset({"image/jpeg"}),
            max_suggestions_per_day=3,
            snooze_cooldown_days=30,
            suggestion_threshold=0.45,
            maturation_horizon_days=180,
            min_days_before_return=7,
        )
        container = build_container(settings, clock=FrozenClock(T0))
        client = TestClient(create_app(settings, container=container))
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        container.close()

    def test_no_endpoint_accepts_a_location(self, api):
        """PRD 46 - Anuvritti must never become child GPS."""
        schema = api.client.get("/openapi.json").json()
        forbidden = ("latitude", "longitude", "gps", "geo", "coordinates", "screen_time")
        assert not [w for w in forbidden if w in str(schema).lower()]
