"""TASK-1411 - The published terms tested against the code.

PRD 44, PRD 47.

Every promise the privacy policy makes has an assertion behind it, and a broken
promise fails the build.
"""

from __future__ import annotations

import json
from pathlib import Path

from anuvritti.domain.entitlement import EntitlementPlan, EntitlementStatus, FamilyEntitlement
from anuvritti.shared.identity import FamilyId

ROOT = Path(__file__).resolve().parents[2]


def test_promise_no_third_party_ad_trackers_in_client_manifest() -> None:
    """Policy promise: We do not embed ad networks or tracking pixels."""
    package_json = ROOT / "apps" / "anuvritti" / "package.json"
    assert package_json.exists()
    data = json.loads(package_json.read_text(encoding="utf-8"))

    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}

    forbidden_sdk_substrings = [
        "google-analytics",
        "firebase-analytics",
        "facebook",
        "adjust",
        "appsflyer",
        "mixpanel",
        "amplitude",
        "segment",
        "sentry",
        "datadog",
    ]

    for dep_name in deps:
        for forbidden in forbidden_sdk_substrings:
            assert forbidden not in dep_name.lower(), (
                f"Forbidden third-party tracker found in dependencies: {dep_name}"
            )


def test_promise_archive_sovereignty_and_export_integrity() -> None:
    """Policy promise: Your data is always exportable in standard formats."""
    entitlement = FamilyEntitlement(
        family_id=FamilyId("fam-pol-1"),
        plan=EntitlementPlan.FREE,
        status=EntitlementStatus.CANCELLED,
    )
    assert entitlement.can_export is True
    assert entitlement.can_read is True


def test_promise_no_surveillance_telemetry() -> None:
    """Policy promise: Telemetry is strictly aggregated and family-blind."""
    from anuvritti.application.analytics import BlindAnalyticsUseCase
    from anuvritti.shared.clock import SystemClock

    analytics = BlindAnalyticsUseCase(clock=SystemClock())
    res = analytics.record_counter("health_ping", 1, metadata={"family_id": "fam-123"})
    assert res.is_err()  # Proves telemetry refuses family identification
