"""TASK-1110 - Blue-Green Release & Error Budget Rollback (HARDENING 5.4).

Verifies that:
1. Candidate slot is checked before traffic cutover.
2. Healthy releases complete cleanly.
3. Post-cutover error budget burn triggers automatic instant rollback to previous slot.
"""

from __future__ import annotations

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
