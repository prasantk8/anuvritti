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


def test_no_advisory_is_accepted_and_the_compatibility_patch_is_pinned():
    assert "nodes.length !== 0" in GATE
    assert 'xcodePackage.version !== "3.0.1"' in GATE
    assert 'uuidPackage.version !== "11.1.1"' in GATE
    assert "GHSA-w5hq-g745-h8pq" in RISK


def test_any_new_audit_node_fails_instead_of_being_implicitly_accepted():
    assert "npm advisory set changed" in GATE
    assert "Object.keys(report.vulnerabilities" in GATE


def test_xcode_compatibility_is_checked_against_installed_source_and_runtime():
    assert 'const xcodeRoot = "node_modules/xcode/lib"' in GATE
    assert "uuid.v4()" in GATE
    assert "v(?:1|3|5|6|7)" in GATE
    assert "project.generateUuid()" in GATE


def test_install_patch_has_provenance_and_an_upstream_retirement_tripwire():
    patch = (ROOT / "scripts" / "patch-xcode-uuid.mjs").read_text()
    assert "sha512-kCz5k7J7XbJtjABO" in patch
    assert 'license: "Apache-2.0"' in patch
    assert "remove or re-review" in patch
    assert '"postinstall": "node scripts/patch-xcode-uuid.mjs"' in PACKAGE
