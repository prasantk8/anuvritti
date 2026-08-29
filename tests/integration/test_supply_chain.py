"""TASK-1106 - Supply Chain & Attested SBOM (HARDENING 5.3).

Verifies that:
1. Pinned dependency manifests generate a reproducible CycloneDX SBOM.
2. Every component has a purl, version, and SHA-256 integrity hash.
3. Attestation digest is cryptographically reproducible.
"""

from __future__ import annotations

from scripts.sbom import (
    compute_sbom_attestation,
    generate_sbom,
    get_node_components,
    get_python_components,
)


def test_python_components_contain_valid_hashes():
    comps = get_python_components()
    assert len(comps) >= 4  # fastapi, uvicorn, pydantic, cryptography, etc.
    for c in comps:
        assert c["type"] == "library"
        assert c["purl"].startswith("pkg:pypi/")
        assert len(c["hashes"]) > 0
        assert c["hashes"][0]["alg"] == "SHA-256"
        assert len(c["hashes"][0]["content"]) == 64


def test_node_components_are_extracted_from_workspaces():
    comps = get_node_components()
    assert len(comps) >= 10
    names = {c["name"] for c in comps}
    assert "react" in names or "expo" in names
    for c in comps:
        assert c["purl"].startswith("pkg:npm/")
        assert len(c["hashes"]) > 0
        assert c["hashes"][0]["alg"] == "SHA-256"


def test_cyclonedx_sbom_structure():
    sbom = generate_sbom()
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert sbom["serialNumber"].startswith("urn:uuid:")
    assert sbom["metadata"]["component"]["name"] == "anuvritti"
    assert len(sbom["components"]) > 10


def test_sbom_attestation_digest_is_deterministic():
    sbom1 = generate_sbom()
    digest1 = compute_sbom_attestation(sbom1)

    sbom2 = generate_sbom()
    digest2 = compute_sbom_attestation(sbom2)

    assert digest1 == digest2
    assert len(digest1) == 64
