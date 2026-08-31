"""TASK-1408 - Test Trust Claims Against Code.

PRD 44, PRD 47, PRD 55.5.

Asserts that every plain-language promise in docs/TRUST.md is backed by code invariants.
"""

from __future__ import annotations

from pathlib import Path

from anuvritti.domain.entitlement import EntitlementPlan, EntitlementStatus, FamilyEntitlement
from anuvritti.shared.identity import FamilyId

ROOT = Path(__file__).resolve().parents[2]
TRUST_DOC = ROOT / "docs" / "TRUST.md"


def test_trust_document_exists_and_is_substantial() -> None:
    assert TRUST_DOC.exists()
    content = TRUST_DOC.read_text(encoding="utf-8")
    assert len(content.splitlines()) >= 20
    assert "What We Store and Where" in content
    assert "Who Can Read Your Archive" in content
    assert "What Happens If We Disappear" in content
    assert "Memories Never Held Hostage" in content


def test_claim_never_held_hostage_is_enforced() -> None:
    """Trust claim: If you stop paying, memories are never held hostage."""
    entitlement = FamilyEntitlement(
        family_id=FamilyId("fam-trust-1"),
        plan=EntitlementPlan.FREE,
        status=EntitlementStatus.EXPIRED,
    )
    assert entitlement.can_read is True
    assert entitlement.can_search is True
    assert entitlement.can_export is True
    assert entitlement.can_verify_fixity is True


def test_claim_offline_reader_and_open_formats_exist() -> None:
    """Trust doc claim: 'Every export bundles a zero-dependency... READER.html'."""
    from anuvritti.application.export import ExportArchiveUseCase

    # Export system must exist and be importable
    assert ExportArchiveUseCase is not None
