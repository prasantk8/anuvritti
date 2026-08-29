"""TASK-401 - observability (PRD 53, 63.4).

Two obligations pull against each other here: an operator must be able to see that the
system is healthy, and a family's archive must not leak into the telemetry that proves it.
Both are tested.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import SequentialIdGenerator
from tests.support.http import PairedClient

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path):
    clock = FrozenClock(NOW)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "o.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    test_client = PairedClient(create_app(settings, container=container))
    test_client.clock = clock  # type: ignore[attr-defined]
    test_client.container = container  # type: ignore[attr-defined]
    yield test_client
    container.close()


@pytest.fixture
def seeded(client):
    family = client.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    child = client.post(
        f"/v1/families/{family['id']}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    ).json()
    return {"family_id": family["id"], "papa_id": family["members"][0]["id"], "child": child["id"]}


class TestHealthAndReadiness:
    def test_health_is_cheap_and_always_answers(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_ping_responds_with_pong_for_cron_and_probes(self, client):
        response = client.get("/health/ping")
        assert response.status_code == 200
        assert response.text == "pong\n"

    def test_readiness_checks_the_archive_is_reachable(self, client):
        body = client.get("/ready").json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"

    def test_readiness_reports_whether_media_is_encrypted(self, client):
        assert client.get("/ready").json()["checks"]["encryption_at_rest"] == "on"

    def test_readiness_reports_not_ready_when_the_archive_is_gone(self, client):
        client.container.connection.close()
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"

    def test_operational_endpoints_are_not_in_the_public_api_schema(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for path in ("/health", "/ready", "/metrics"):
            assert path not in paths


class TestRequestCorrelation:
    def test_every_response_carries_a_request_id(self, client):
        assert client.get("/health").headers["x-request-id"]

    def test_a_supplied_request_id_is_honoured(self, client):
        response = client.get("/health", headers={"x-request-id": "trace-me"})
        assert response.headers["x-request-id"] == "trace-me"

    def test_the_request_id_appears_in_the_log_line(self, client, capsys):
        client.get("/health", headers={"x-request-id": "trace-me"})
        assert "trace-me" in capsys.readouterr().out

    def test_ids_differ_between_requests(self, client):
        first = client.get("/health").headers["x-request-id"]
        second = client.get("/health").headers["x-request-id"]
        assert first != second


class TestStructuredLogs:
    def test_access_logs_are_one_json_object_per_line(self, client, capsys):
        client.get("/health")
        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        for line in lines:
            payload = json.loads(line)
            assert {"timestamp", "level", "logger", "message"} <= set(payload)

    def test_access_logs_record_method_route_status_and_duration(self, client, capsys):
        client.get("/health")
        entry = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert entry["method"] == "GET"
        assert entry["route"] == "/health"
        assert entry["status"] == 200
        assert isinstance(entry["duration_ms"], int | float)

    def test_logs_never_contain_a_request_body(self, client, seeded, capsys):
        client.post(
            "/v1/little-things",
            json={
                "family_id": seeded["family_id"],
                "author_id": seeded["papa_id"],
                "text": "He called the moon a broken sun.",
            },
        )
        assert "broken sun" not in capsys.readouterr().out

    def test_logs_never_contain_a_response_body(self, client, seeded, capsys):
        client.get(f"/v1/families/{seeded['family_id']}")
        assert "Aarav" not in capsys.readouterr().out


class TestMetrics:
    def test_metrics_are_prometheus_text(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "# HELP" in response.text
        assert "# TYPE" in response.text

    def test_http_requests_are_counted_by_route_and_status(self, client):
        client.get("/health")
        client.get("/health")
        text = client.get("/metrics").text
        assert 'anuvritti_http_requests_total{route="/health",status="200"} 2' in text

    def test_the_route_label_is_a_template_not_a_populated_path(self, client, seeded):
        client.get(f"/v1/families/{seeded['family_id']}")
        text = client.get("/metrics").text
        assert "{family_id}" in text
        assert seeded["family_id"] not in text

    def test_the_primary_north_star_is_exposed(self, client, seeded):
        """PRD 53 - Intent -> Moment conversion is the number that matters."""
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": seeded["family_id"],
                "owner_id": seeded["papa_id"],
                "source": {"kind": "TEXT", "text": "science experiment"},
            },
        ).json()["id"]
        client.clock.advance(days=100)
        client.post(f"/v1/sparks/{spark_id}/done", json={"created_by": seeded["papa_id"]})

        text = client.get("/metrics").text
        assert "anuvritti_sparks_captured_total 1" in text
        assert "anuvritti_moments_created_total 1" in text
        assert "anuvritti_intent_to_moment_ratio 1.0000" in text

    def test_the_ratio_is_zero_rather_than_undefined_on_an_empty_archive(self, client):
        assert "anuvritti_intent_to_moment_ratio 0.0000" in client.get("/metrics").text

    def test_the_anti_metrics_are_exposed_and_labelled_as_such(self, client):
        """PRD 53 - notification volume is instrumented so it can be watched going DOWN."""
        text = client.get("/metrics").text
        assert "anti-metrics" in text
        assert "anuvritti_suggestions_emitted_total" in text
        assert "watched going DOWN" in text

    def test_suggestions_are_counted_when_the_product_interrupts_a_family(self, client, seeded):
        client.post(
            "/v1/sparks",
            json={
                "family_id": seeded["family_id"],
                "owner_id": seeded["papa_id"],
                "subject_child_id": seeded["child"],
                "source": {"kind": "TEXT", "text": "science experiment to do together"},
            },
        )
        assert "anuvritti_suggestions_emitted_total 0" in client.get("/metrics").text

        client.clock.advance(days=245)
        client.get(
            "/v1/return/worth-bringing-back",
            params={"family_id": seeded["family_id"], "actor_id": seeded["papa_id"]},
        )
        assert "anuvritti_suggestions_emitted_total 1" in client.get("/metrics").text

    def test_metrics_carry_no_family_identifying_labels(self, client, seeded):
        client.get(f"/v1/families/{seeded['family_id']}")
        text = client.get("/metrics").text
        assert seeded["family_id"] not in text
        assert "Aarav" not in text
        assert "Our family" not in text

    def test_server_errors_are_counted_separately(self, client):
        from anuvritti.interfaces.http.observability import Metrics

        metrics = Metrics()
        metrics.observe("/v1/sparks", 500, 12.0)
        metrics.observe("/v1/sparks", 200, 3.0)
        assert metrics.errors["/v1/sparks"] == 1
        assert metrics.request_count == 2
