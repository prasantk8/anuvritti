"""TASK-1410 - Incident response rehearsal.

HARDENING 5.4, PRD 44.
"""

from __future__ import annotations

from pathlib import Path

from anuvritti.infrastructure.release import BlueGreenDeployer, SlotConfig

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_DOC = ROOT / "docs" / "RUNBOOK.md"


def test_runbook_document_exists_and_covers_incident_response() -> None:
    assert RUNBOOK_DOC.exists()
    content = RUNBOOK_DOC.read_text(encoding="utf-8")
    assert "Automated Rollback & Error Budget Depletion" in content
    assert "Family Notification Protocol" in content


def test_incident_drill_triggers_clean_rollback_and_notification() -> None:
    blue = SlotConfig(name="blue", port=8001, version="1.0.0")
    green = SlotConfig(name="green", port=8002, version="1.1.0-bad")
    deployer = BlueGreenDeployer(active_slot=blue, candidate_slot=green)

    rolled_back_slot = None

    def fake_health(slot: SlotConfig) -> bool:
        return True

    def fake_cutover(slot: SlotConfig) -> bool:
        return True

    def fake_monitor_burn(slot: SlotConfig) -> bool:
        # Simulate error budget failure
        return False

    def fake_rollback(slot: SlotConfig) -> bool:
        nonlocal rolled_back_slot
        rolled_back_slot = slot.name
        return True

    success, msg = deployer.execute_release(
        health_check_fn=fake_health,
        cutover_fn=fake_cutover,
        monitor_burn_fn=fake_monitor_burn,
        rollback_fn=fake_rollback,
    )

    assert success is False
    assert "Error budget burn rate exceeded; automatically rolled back" in msg
    assert deployer.current_live == "blue"
    assert rolled_back_slot == "blue"
