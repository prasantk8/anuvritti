"""TASK-1110 - Blue-Green Release & Error Budget Rollback (HARDENING 5.4).

Verifies that:
1. Candidate slot is checked before traffic cutover.
2. Healthy releases complete cleanly and promote candidate.
3. Post-cutover error budget burn triggers automatic instant rollback.
4. Caddy cutover and rollback functions persist upstream target states.
"""

from __future__ import annotations

from pathlib import Path

from scripts.release import cutover_caddy, evaluate_slot_slo_burn, rollback_caddy

from anuvritti.infrastructure.release import BlueGreenDeployer, SlotConfig


def test_successful_blue_green_release():
    blue = SlotConfig(name="blue", port=8001, version="v1.0.0")
    green = SlotConfig(name="green", port=8002, version="v1.1.0")

    deployer = BlueGreenDeployer(blue, green)

    ok, msg = deployer.execute_release(
        health_check_fn=lambda _slot: True,
        cutover_fn=lambda _slot: True,
        monitor_burn_fn=lambda _slot: True,  # Error budget healthy
        rollback_fn=lambda _slot: True,
    )

    assert ok is True
    assert "successfully deployed" in msg
    assert deployer.current_live == "green"
    assert deployer.active.version == "v1.1.0"


def test_aborts_if_candidate_health_check_fails():
    blue = SlotConfig(name="blue", port=8001, version="v1.0.0")
    green = SlotConfig(name="green", port=8002, version="v1.1.0")

    deployer = BlueGreenDeployer(blue, green)

    ok, msg = deployer.execute_release(
        health_check_fn=lambda _slot: False,  # Candidate unhealthy
        cutover_fn=lambda _slot: True,
        monitor_burn_fn=lambda _slot: True,
        rollback_fn=lambda _slot: True,
    )

    assert ok is False
    assert "Pre-flight health check failed" in msg
    assert deployer.current_live == "blue"


def test_automatic_rollback_on_error_budget_burn():
    blue = SlotConfig(name="blue", port=8001, version="v1.0.0")
    green = SlotConfig(name="green", port=8002, version="v1.1.0")

    rolled_back_to = []

    def mock_rollback(slot: SlotConfig) -> bool:
        rolled_back_to.append(slot.name)
        return True

    deployer = BlueGreenDeployer(blue, green)

    ok, msg = deployer.execute_release(
        health_check_fn=lambda _slot: True,
        cutover_fn=lambda _slot: True,
        monitor_burn_fn=lambda _slot: False,  # Error budget exceeded / burn detected!
        rollback_fn=mock_rollback,
    )

    assert ok is False
    assert "rolled back" in msg
    assert deployer.current_live == "blue"
    assert rolled_back_to == ["blue"]
    assert "rollback_to_blue" in deployer.history


def test_evaluate_slot_slo_burn_with_prometheus_metrics():
    # 1. Healthy metrics exposition (1000 requests, 0 errors)
    healthy_metrics = """
    # HELP anuvritti_http_requests_total Total HTTP requests
    # TYPE anuvritti_http_requests_total counter
    anuvritti_http_requests_total{route="/v1/sparks",status="200"} 1000
    anuvritti_http_requests_errors_total{route="/v1/sparks"} 0
    """
    assert evaluate_slot_slo_burn(healthy_metrics) is True

    # 2. Critical error burn (100 requests, 15 errors -> 15% error rate on 99.9% SLO)
    critical_burn_metrics = """
    # HELP anuvritti_http_requests_total Total HTTP requests
    # TYPE anuvritti_http_requests_total counter
    anuvritti_http_requests_total{route="/v1/sparks",status="200"} 85
    anuvritti_http_requests_total{route="/v1/sparks",status="500"} 15
    anuvritti_http_requests_errors_total{route="/v1/sparks"} 15
    """
    assert evaluate_slot_slo_burn(critical_burn_metrics) is False


def test_caddy_cutover_and_rollback_helpers(tmp_path: Path, monkeypatch):
    test_state_file = tmp_path / "caddy_upstream.json"
    monkeypatch.setattr("scripts.release.CADDY_UPSTREAM_FILE", test_state_file)

    blue = SlotConfig(name="blue", port=8001, version="v1.0.0")
    green = SlotConfig(name="green", port=8002, version="v1.1.0")

    assert cutover_caddy(green) is True
    assert test_state_file.exists()
    assert '"port": 8002' in test_state_file.read_text()

    assert rollback_caddy(blue) is True
    assert '"port": 8001' in test_state_file.read_text()
    assert '"rolled_back"' in test_state_file.read_text()
