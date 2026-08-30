"""TASK-1301: Family Archive Format Specification Verification (PRD 45, PRD 52, PRD 37).

Verifies:
1. docs/contracts/archive.md exists and is complete.
2. JSON schemas and code snippets in the contract are valid and parseable.
3. Required files, discrete provenance fields, and checksum structures are strictly defined.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CONTRACT_PATH = Path("docs/contracts/archive.md")


def test_archive_contract_exists():
    assert CONTRACT_PATH.exists(), "docs/contracts/archive.md must exist"
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "Family Archive Format Specification" in content
    assert "v1.0" in content


def test_archive_contract_defines_required_files():
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    required_files = [
        "archive.json",
        "manifest.json",
        "sparks.json",
        "moments.json",
        "voice_notes.json",
        "little_things.json",
        "lexicon.json",
        "films/",
        "media/",
        "READER.html",
    ]
    for filename in required_files:
        assert filename in content, f"Contract must specify {filename}"


def test_all_contract_json_blocks_are_valid():
    """Extract every json block in docs/contracts/archive.md and ensure valid JSON syntax."""
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    json_blocks = re.findall(r"```json\s+(.*?)\s+```", content, re.DOTALL)
    assert len(json_blocks) >= 5, "Contract must contain concrete JSON schema examples"

    for i, block in enumerate(json_blocks):
        try:
            parsed = json.loads(block)
            assert parsed is not None
        except json.JSONDecodeError as exc:
            pytest.fail(f"Invalid JSON in block {i} of archive.md: {exc}\nBlock content:\n{block}")


def test_archive_json_structure():
    """Validate the root archive.json structure in the specification."""
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    match = re.search(r"### 2\.1 `archive\.json`.*?\n```json\s+(.*?)\s+```", content, re.DOTALL)
    assert match is not None
    data = json.loads(match.group(1))

    assert data["format_version"] == "1.0"
    assert "archive_id" in data
    assert "family" in data
    assert "children" in data
    assert "members" in data
    assert "counts" in data
    assert data["family"]["id"] == "fam-1"
    assert len(data["children"]) >= 1


def test_manifest_structure():
    """Validate manifest.json schema with SHA-256 checksums."""
    content = CONTRACT_PATH.read_text(encoding="utf-8")
    match = re.search(r"### 2\.2 `manifest\.json`.*?\n```json\s+(.*?)\s+```", content, re.DOTALL)
    assert match is not None
    data = json.loads(match.group(1))

    assert data["algorithm"] == "SHA-256"
    assert "files" in data
    for item in data["files"]:
        assert "relative_path" in item
        assert "byte_size" in item
        assert "mime_type" in item
        assert "sha256" in item
        assert len(item["sha256"]) == 64


def test_discrete_provenance_in_sparks_and_voice():
    """Ensure provenance is represented as discrete fields, never opaque blobs (ADR-0005)."""
    content = CONTRACT_PATH.read_text(encoding="utf-8")

    # Sparks provenance
    sparks_match = re.search(
        r"### 2\.3 `sparks\.json`.*?\n```json\s+(.*?)\s+```", content, re.DOTALL
    )
    assert sparks_match is not None
    sparks_data = json.loads(sparks_match.group(1))
    spark = sparks_data[0]
    for field in ("intent", "category", "age_range"):
        assert "source" in spark[field]
        assert "confidence" in spark[field]
        assert "overridden" in spark[field]

    # Voice provenance
    voice_match = re.search(
        r"### 2\.5 `voice_notes\.json`.*?\n```json\s+(.*?)\s+```", content, re.DOTALL
    )
    assert voice_match is not None
    voice_data = json.loads(voice_match.group(1))
    voice = voice_data[0]
    assert "transcript" in voice
    assert voice["transcript"]["source"] == "ON_DEVICE_WHISPER"
    assert "engine" in voice["transcript"]
    assert "confidence" in voice["transcript"]
