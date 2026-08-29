"""TASK-1011 - Privacy Manifest & Telemetry Auditor (PRD 44, PRD 46, HARDENING 5.3).

Verifies that:
1. Privacy manifests are generated directly from code facts.
2. Tracking is strictly False and tracking domains are empty.
3. No dependencies or permissions can leak telemetry or access unauthorized hardware.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.privacy_manifest import (
    audit_mobile_permissions,
    audit_package_dependencies,
    generate_apple_privacy_manifest,
    generate_google_play_data_safety,
)

ROOT = Path(__file__).resolve().parents[2]


def test_apple_privacy_manifest_guarantees_zero_tracking():
    manifest = generate_apple_privacy_manifest()
    assert manifest["NSPrivacyTracking"] is False
    assert manifest["NSPrivacyTrackingDomains"] == []

    for item in manifest["NSPrivacyCollectedDataTypes"]:
        assert item["NSPrivacyCollectedDataTypeLinked"] is False
        assert item["NSPrivacyCollectedDataTypeTracking"] is False
        assert item["NSPrivacyCollectedDataTypePurposes"] == [
            "NSPrivacyCollectedDataTypePurposeAppFunctionality"
        ]


def test_google_play_data_safety_guarantees_zero_third_party_sharing():
    safety = generate_google_play_data_safety()
    assert safety["data_shared"] == []
    assert safety["security_practices"]["data_encrypted_in_transit"] is True
    assert safety["security_practices"]["data_encrypted_at_rest"] is True
    assert safety["security_practices"]["user_can_request_deletion"] is True


def test_production_app_contains_zero_tracking_sdks():
    pkg_path = ROOT / "apps" / "anuvritti" / "package.json"
    violations = audit_package_dependencies(pkg_path)
    assert violations == [], f"Found unexpected tracking SDKs: {violations}"


def test_production_app_requests_only_permitted_permissions():
    app_json_path = ROOT / "apps" / "anuvritti" / "app.json"
    violations = audit_mobile_permissions(app_json_path)
    assert violations == [], f"Found unlisted permissions: {violations}"


def test_auditor_catches_invasive_tracking_dependencies(tmp_path: Path):
    bad_pkg = tmp_path / "package.json"
    bad_pkg.write_text(
        json.dumps(
            {
                "dependencies": {
                    "react": "19.0.0",
                    "react-native-mixpanel": "1.0.0",
                    "@segment/analytics-react-native": "2.0.0",
                }
            }
        )
    )
    violations = audit_package_dependencies(bad_pkg)
    assert len(violations) == 2
    assert any("mixpanel" in v for v in violations)
    assert any("analytics" in v for v in violations)


def test_auditor_catches_unlisted_invasive_permissions(tmp_path: Path):
    bad_app_json = tmp_path / "app.json"
    bad_app_json.write_text(
        json.dumps(
            {
                "expo": {
                    "plugins": [
                        [
                            "expo-location",
                            {"locationAlwaysPermission": "Track child location continuously"},
                        ]
                    ]
                }
            }
        )
    )
    violations = audit_mobile_permissions(bad_app_json)
    assert len(violations) == 1
    assert "locationAlwaysPermission" in violations[0]
