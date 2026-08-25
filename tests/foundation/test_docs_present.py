"""TASK-404 - the documentation is a deliverable, so its promises are checked.

Docs rot quietly. These tests catch the two failures that matter: a document that has
gone missing, and a document that describes something the code no longer does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

REQUIRED = [
    "README.md",
    "CLAUDE.md",
    "docs/PRD.md",
    "docs/ARCHITECTURE.md",
    "docs/HARDENING.md",
    "docs/RUNBOOK.md",
    "docs/contracts/openapi.yaml",
    "docs/contracts/events.md",
    "docs/contracts/errors.md",
]


class TestEverythingExists:
    @pytest.mark.parametrize("path", REQUIRED)
    def test_the_document_exists_and_is_not_a_stub(self, path: str):
        target = ROOT / path
        assert target.is_file(), f"{path} is missing"
        assert len(target.read_text().strip()) > 400, f"{path} is a stub"

    def test_every_adr_referenced_by_the_architecture_exists(self):
        architecture = (DOCS / "ARCHITECTURE.md").read_text()
        for adr in re.findall(r"\(architecture/(ADR-[^)]+\.md)\)", architecture):
            assert (DOCS / "architecture" / adr).is_file(), adr

    def test_there_is_at_least_one_adr_per_major_decision(self):
        assert len(list((DOCS / "architecture").glob("ADR-*.md"))) >= 5

    def test_every_adr_records_a_status_and_consequences(self):
        for adr in (DOCS / "architecture").glob("ADR-*.md"):
            text = adr.read_text()
            assert "**Status:**" in text, adr.name
            assert "## Consequences" in text or "## Decision" in text, adr.name


class TestTheContractsMatchTheCode:
    def test_the_openapi_document_parses(self):
        import yaml

        spec = yaml.safe_load((DOCS / "contracts" / "openapi.yaml").read_text())
        assert spec["openapi"].startswith("3.")
        assert spec["paths"]

    def test_the_documented_error_codes_all_exist(self):
        from anuvritti.shared.errors import ErrorCode

        documented = set(
            re.findall(
                r"^\| `([A-Z_]+)` \|", (DOCS / "contracts" / "errors.md").read_text(), re.MULTILINE
            )
        )
        assert documented
        assert documented <= {code.value for code in ErrorCode}

    def test_the_documented_events_all_exist(self):
        from anuvritti.domain import events

        documented = set(
            re.findall(
                r"^\| `(\w+)` \|", (DOCS / "contracts" / "events.md").read_text(), re.MULTILINE
            )
        )
        implemented = {name for name in dir(events) if name[0].isupper()}
        assert documented
        assert documented <= implemented, f"documented but missing: {documented - implemented}"

    def test_the_six_v0_intents_in_the_contract_match_the_code(self):
        import yaml

        from anuvritti.domain.values import IntentType

        spec = yaml.safe_load((DOCS / "contracts" / "openapi.yaml").read_text())
        documented = set(spec["components"]["schemas"]["IntentType"]["enum"])
        assert documented == {i.value for i in IntentType.v0_set()}


class TestTheRunbookIsHonest:
    def test_it_documents_backup_and_restore(self):
        runbook = (DOCS / "RUNBOOK.md").read_text()
        assert ".backup" in runbook
        assert "Restore" in runbook

    def test_it_documents_export_and_delete(self):
        """PRD 44 - anyone operating this should know these are features, not tickets."""
        runbook = (DOCS / "RUNBOOK.md").read_text()
        assert "/export" in runbook
        assert "DELETE" in runbook

    def test_it_warns_that_v0_has_no_authentication(self):
        """An honest runbook names the biggest open risk rather than burying it."""
        assert "no authentication" in (DOCS / "RUNBOOK.md").read_text().lower()

    def test_the_readme_carries_the_same_warning(self):
        assert "no authentication" in (ROOT / "README.md").read_text().lower()

    def test_it_names_every_endpoint_it_tells_an_operator_to_call(self):
        runbook = (DOCS / "RUNBOOK.md").read_text()
        for endpoint in ("/health", "/ready", "/metrics"):
            assert endpoint in runbook


class TestTheHardeningReportIsHonest:
    def test_it_lists_open_items_rather_than_only_successes(self):
        """A hardening report with no open items is a marketing document."""
        report = (DOCS / "HARDENING.md").read_text()
        assert "Open items" in report
        assert "HIGH" in report

    def test_it_names_the_missing_authentication_explicitly(self):
        assert "no authentication" in (DOCS / "HARDENING.md").read_text().lower()

    def test_it_records_the_findings_fixed_during_the_build(self):
        assert "Findings raised and fixed" in (DOCS / "HARDENING.md").read_text()

    def test_it_has_a_threat_model(self):
        report = (DOCS / "HARDENING.md").read_text()
        assert "Threat model" in report
        assert report.count("| T") >= 8
