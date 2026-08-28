"""TASK-732 — accepted npm risk is narrow, executable and reviewable."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = (ROOT / "package.json").read_text()
GATE = (ROOT / "scripts" / "audit-javascript.mjs").read_text()
RISK = (ROOT / "docs" / "DEPENDENCY-RISK.md").read_text()
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()


def test_audit_gate_is_part_of_the_security_job():
    assert '"audit": "node scripts/audit-javascript.mjs"' in PACKAGE
    assert "npm run audit" in CI


def test_acceptance_names_the_advisory_and_affected_apis():
    assert "1119441" in GATE
    assert "GHSA-w5hq-g745-h8pq" in RISK
    for version in ("v3", "v5", "v6"):
        assert version in RISK


def test_any_new_audit_node_fails_instead_of_being_implicitly_accepted():
    assert "npm advisory set changed" in GATE
    assert "Object.keys(report.vulnerabilities" in GATE


def test_reachability_assumption_is_checked_against_installed_xcode_source():
    assert 'const xcodeRoot = "node_modules/xcode/lib"' in GATE
    assert "uuid.v4()" in GATE
    assert "v(?:3|5|6)" in GATE
