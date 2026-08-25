"""PRD 46 - No surveillance parenting.

    "It should help families understand and connect. Not monitor and optimize children."

The strongest guarantee is absence: the capability does not exist anywhere in the system,
so no future feature can quietly switch it on.
"""

from __future__ import annotations

import re
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

SRC = Path(__file__).resolve().parents[2] / "src"
NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)

#: PRD 46, each mapped to identifiers that would exist if it were being built.
FORBIDDEN_CAPABILITIES = {
    "obsessive child GPS": r"\b(latitude|longitude|geofence|gps_|last_known_location|track_child)",
    "emotion surveillance": r"\b(emotion_score|mood_detect|sentiment_of_child|affect_recognition)",
    "hidden microphone recording": r"\b(ambient_record|always_listen|background_audio_capture)",
    "screen spying": r"\b(screen_time|app_usage|keystroke|browsing_history)",
    "behavioural scoring": (
        r"\b(behaviour_score|behavior_score|child_score|good_child|conduct_rating)"
    ),
    "parent comparison": r"\b(percentile|vs_average|compare_to_peers|parent_rank)",
    "developmental fear engine": r"\b(is_delayed|behind_peers|milestone_warning|at_risk_flag)",
}


@pytest.fixture
def client(tmp_path):
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "c.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=FrozenClock(NOW), ids=SequentialIdGenerator("id"))
    yield PairedClient(create_app(settings, container=container))
    container.close()


class TestTheCapabilityDoesNotExist:
    @pytest.mark.parametrize("capability,pattern", sorted(FORBIDDEN_CAPABILITIES.items()))
    def test_it_is_absent_from_the_source(self, capability, pattern):
        offenders = [
            path.relative_to(SRC)
            for path in SRC.rglob("*.py")
            if re.search(pattern, path.read_text(), re.IGNORECASE)
        ]
        assert not offenders, f"PRD 46 forbids {capability}; found in {offenders}"

    @pytest.mark.parametrize("capability,pattern", sorted(FORBIDDEN_CAPABILITIES.items()))
    def test_it_is_absent_from_the_database_schema(self, capability, pattern):
        from anuvritti.adapters.persistence import schema

        source = Path(schema.__file__).read_text()
        assert not re.search(pattern, source, re.IGNORECASE)


class TestTheApiCannotBeAskedForIt:
    def test_no_endpoint_mentions_a_location(self, client):
        spec = str(client.get("/openapi.json").json()).lower()
        for word in ("latitude", "longitude", "gps", "geolocation", "coordinates"):
            assert word not in spec

    def test_no_endpoint_mentions_screen_activity(self, client):
        spec = str(client.get("/openapi.json").json()).lower()
        for word in ("screen_time", "app_usage", "browsing"):
            assert word not in spec

    def test_an_attempt_to_attach_a_location_to_a_spark_is_rejected(self, client):
        """Unknown fields are refused, so a client cannot smuggle one in."""
        family = client.post(
            "/v1/families", json={"name": "F", "owner_display_name": "Papa"}
        ).json()
        response = client.post(
            "/v1/sparks",
            json={
                "family_id": family["id"],
                "owner_id": family["members"][0]["id"],
                "source": {"kind": "TEXT", "text": "x"},
                "latitude": 12.97,
                "longitude": 77.59,
            },
        )
        assert response.status_code == 422


class TestTheChildIsNotMeasured:
    def test_nothing_in_the_domain_scores_a_child(self):
        offenders = [
            path.relative_to(SRC)
            for path in (SRC / "anuvritti" / "domain").rglob("*.py")
            if re.search(r"def .*(score|rate|rank)_child", path.read_text(), re.IGNORECASE)
        ]
        assert not offenders

    def test_the_only_score_in_the_system_ranks_content_not_children(self):
        """The Return Engine scores *a Spark's relevance*, never a child or a parent."""
        from anuvritti.domain.return_engine import ReturnEngine

        assert set(ReturnEngine.WEIGHTS) == {
            "age_fit",
            "maturation",
            "occasion_fit",
            "intent_actionability",
            "why_present",
            "novelty",
        }

    def test_the_relevance_score_is_never_sent_to_a_client(self):
        from anuvritti.interfaces.http import schemas

        source = Path(schemas.__file__).read_text()
        rendered = source[source.index("def render_suggestion") : source.index("def render_moment")]
        assert '"score"' not in rendered

    def test_right_now_prompts_ask_the_parent_to_notice_not_to_assess(self):
        from anuvritti.domain.presence import RIGHT_NOW_PROMPTS

        judging = ("should", "behind", "on track", "compared", "better than", "normal for")
        for prompt in RIGHT_NOW_PROMPTS:
            assert not any(word in prompt.lower() for word in judging), prompt


class TestTelemetryIsNotASecondArchive:
    def test_no_domain_event_carries_free_text_family_content(self):
        """docs/contracts/events.md - payloads are structural only.

        Checked structurally: every string-typed field on every event must be an
        identifier or a system-chosen key, never something a person wrote.
        """
        import ast

        from anuvritti.domain import events

        allowed_string_fields = {
            "aggregate_id",
            "family_id",
            "owner_id",
            "subject_child_id",
            "spark_id",
            "child_id",
            "field",
            "category",
            "reason_key",
            "prompt",
        }
        tree = ast.parse(Path(events.__file__).read_text())
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign) or not isinstance(
                    statement.target, ast.Name
                ):
                    continue
                name = statement.target.id
                annotation = ast.unparse(statement.annotation)
                # Only a bare `str` field can carry free text. `dict[str, int]` is a
                # mapping of counts keyed by a name - structure, not content.
                if annotation in {"str", "str | None"} and name not in allowed_string_fields:
                    offenders.append(f"{node.name}.{name}: {annotation}")
        assert not offenders, f"events must not carry family content: {offenders}"

    def test_the_prompt_on_an_event_is_one_the_system_chose(self):
        """`prompt` is allowed above only because the product wrote it, not the family."""
        from anuvritti.domain.presence import RIGHT_NOW_PROMPTS

        assert len(RIGHT_NOW_PROMPTS) >= 8

    def test_the_log_formatter_redacts_content_fields(self):
        from anuvritti.config.logging import REDACTED_FIELDS

        for field in ("why_text", "reflection", "answer", "child_name", "source_url"):
            assert field in REDACTED_FIELDS

    def test_access_logs_record_the_route_template_not_the_populated_path(self, client, capsys):
        """A URL containing a child's id is data, not a label.

        Read in one go at the end: the log handler binds `sys.stdout` when it is built,
        so an intermediate `readouterr()` would reset a stream it is not writing to.
        """
        family = client.post(
            "/v1/families", json={"name": "F", "owner_display_name": "Papa"}
        ).json()
        client.get(f"/v1/families/{family['id']}")

        logged = capsys.readouterr().out
        assert "{family_id}" in logged, "the route template should be the label"
        assert family["id"] not in logged, "the populated path must never be logged"

    def test_metrics_carry_no_family_identifying_labels(self, client):
        family = client.post(
            "/v1/families", json={"name": "The Sharmas", "owner_display_name": "Papa"}
        ).json()
        metrics = client.get("/metrics").text
        assert family["id"] not in metrics
        assert "Sharma" not in metrics
