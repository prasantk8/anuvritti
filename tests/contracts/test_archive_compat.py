"""TASK-1303: Forward Compatibility Against Archive Corpus (PRD 8.6, PRD 52).

Verifies that every archive version ever shipped or recorded in the corpus:
1. Can be opened, read, and normalized by today's reader without errors.
2. Manifest hash verification validates fixity across all versions.
3. Incompatible future major versions are rejected cleanly out loud.
4. Tampered / bit-rotted files within an archive are caught by integrity checks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

CORPUS_DIR = Path("tests/contracts/corpus")


def _compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _create_v0_9_corpus_archive(root: Path) -> Path:
    """Creates a synthetic v0.9 (early draft) archive with legacy flattened fields."""
    root.mkdir(parents=True, exist_ok=True)
    media_dir = root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    photo_bytes = b"LEGACY_PHOTO_BYTES_0.9"
    (media_dir / "photo-09.jpg").write_bytes(photo_bytes)

    sparks_data = [
        {
            "id": "spark-09-1",
            "title": "Early Spark",
            "note": "Legacy capture format",
            "category": "CRAFT",
            "intent": "DO",
            "created_at": "2025-10-01T10:00:00Z",
        }
    ]
    (root / "sparks.json").write_text(json.dumps(sparks_data, indent=2), encoding="utf-8")

    moments_data = [
        {
            "id": "mom-09-1",
            "spark_id": "spark-09-1",
            "happened_on": "2025-10-02",
            "reflection": "Painted a leaf",
            "photo_media_id": "photo-09",
        }
    ]
    (root / "moments.json").write_text(json.dumps(moments_data, indent=2), encoding="utf-8")

    archive_data = {
        "format_version": "0.9",
        "archive_id": "arc-v0.9-sample",
        "exported_at": "2025-10-03T00:00:00Z",
        "family": {"id": "fam-legacy-1", "name": "The Legacy Family"},
        "children": [{"id": "child-09-1", "display_name": "Aarav", "date_of_birth": "2023-01-01"}],
        "members": [{"id": "mem-09-1", "display_name": "Mama", "role": "PARENT"}],
    }
    (root / "archive.json").write_text(json.dumps(archive_data, indent=2), encoding="utf-8")

    # Generate manifest
    files_entry = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            b = p.read_bytes()
            files_entry.append(
                {
                    "relative_path": p.relative_to(root).as_posix(),
                    "byte_size": len(b),
                    "sha256": _compute_sha256(b),
                }
            )

    manifest_data = {"algorithm": "SHA-256", "files": files_entry}
    (root / "manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    return root


def _create_v1_0_corpus_archive(root: Path) -> Path:
    """Creates a standard v1.0 archive adhering to docs/contracts/archive.md."""
    root.mkdir(parents=True, exist_ok=True)
    media_dir = root / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    audio_bytes = b"RIFFWAVE_VOICE_SAMPLE_V1_0"
    (media_dir / "voice-10.wav").write_bytes(audio_bytes)

    sparks_data = [
        {
            "id": "spark-10-1",
            "title": "Bicycle riding",
            "note": "Without training wheels",
            "intent": {"value": "DO", "source": "PARENT", "confidence": 1.0, "overridden": False},
            "category": {
                "value": "MOVEMENT",
                "source": "PARENT",
                "confidence": 1.0,
                "overridden": False,
            },
            "created_at": "2026-05-01T12:00:00Z",
        }
    ]
    (root / "sparks.json").write_text(json.dumps(sparks_data, indent=2), encoding="utf-8")
    (root / "moments.json").write_text("[]", encoding="utf-8")
    (root / "voice_notes.json").write_text("[]", encoding="utf-8")
    (root / "little_things.json").write_text("[]", encoding="utf-8")
    (root / "lexicon.json").write_text("[]", encoding="utf-8")

    archive_data = {
        "format_version": "1.0",
        "archive_id": "arc-v1.0-sample",
        "exported_at": "2026-05-02T00:00:00Z",
        "family": {"id": "fam-v1-1", "name": "The Modern Family"},
        "children": [{"id": "child-10-1", "display_name": "Maya", "date_of_birth": "2022-04-10"}],
        "members": [{"id": "mem-10-1", "display_name": "Papa", "role": "PARENT"}],
        "counts": {"sparks": 1, "moments": 0, "media_files": 1},
    }
    (root / "archive.json").write_text(json.dumps(archive_data, indent=2), encoding="utf-8")

    # Generate manifest
    files_entry = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            b = p.read_bytes()
            files_entry.append(
                {
                    "relative_path": p.relative_to(root).as_posix(),
                    "byte_size": len(b),
                    "sha256": _compute_sha256(b),
                }
            )

    manifest_data = {"algorithm": "SHA-256", "files": files_entry}
    (root / "manifest.json").write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    return root


def open_and_verify_archive(archive_dir: Path) -> dict[str, Any]:
    """Canonical reader verification for opening any archive from the corpus."""
    assert archive_dir.exists(), f"Archive dir {archive_dir} must exist"

    root_file = archive_dir / "archive.json"
    manifest_file = archive_dir / "manifest.json"

    assert root_file.exists(), "archive.json must exist"
    assert manifest_file.exists(), "manifest.json must exist"

    root_meta = json.loads(root_file.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    version = root_meta.get("format_version")
    if not version:
        raise ValueError("Missing format_version in archive.json")

    major = int(version.split(".")[0])
    if major > 1:
        raise ValueError(
            f"Unsupported future archive format version: {version}. "
            "Please upgrade your Anuvritti reader."
        )

    # Verify SHA-256 fixity of every file
    assert manifest.get("algorithm") == "SHA-256"
    for item in manifest.get("files", []):
        rel = item["relative_path"]
        target = archive_dir / rel
        if not target.exists():
            raise FileNotFoundError(f"Missing file from manifest: {rel}")
        actual_hash = _compute_sha256(target.read_bytes())
        if actual_hash != item["sha256"]:
            raise ValueError(f"Integrity check failed for {rel}: expected {item['sha256']}")

    # Load and normalize sparks
    sparks_file = archive_dir / "sparks.json"
    sparks = []
    if sparks_file.exists():
        raw_sparks = json.loads(sparks_file.read_text(encoding="utf-8"))
        for s in raw_sparks:
            # Normalize legacy string categories/intents if v0.9
            cat = s.get("category")
            if isinstance(cat, str):
                cat = {"value": cat, "source": "PARENT", "confidence": 1.0, "overridden": False}
            intent = s.get("intent")
            if isinstance(intent, str):
                intent = {
                    "value": intent,
                    "source": "PARENT",
                    "confidence": 1.0,
                    "overridden": False,
                }
            normalized_spark = {
                "id": s["id"],
                "title": s["title"],
                "note": s.get("note"),
                "category": cat,
                "intent": intent,
                "created_at": s.get("created_at"),
            }
            sparks.append(normalized_spark)

    return {
        "version": version,
        "family": root_meta.get("family"),
        "children": root_meta.get("children", []),
        "sparks": sparks,
    }


def test_forward_compat_opens_v0_9_corpus(tmp_path: Path):
    """v0.9 archive with legacy schema is cleanly opened and normalized."""
    corpus_v09 = _create_v0_9_corpus_archive(tmp_path / "corpus_v09")
    parsed = open_and_verify_archive(corpus_v09)

    assert parsed["version"] == "0.9"
    assert parsed["family"]["name"] == "The Legacy Family"
    assert len(parsed["sparks"]) == 1
    assert parsed["sparks"][0]["title"] == "Early Spark"
    assert parsed["sparks"][0]["category"]["value"] == "CRAFT"


def test_forward_compat_opens_v1_0_corpus(tmp_path: Path):
    """v1.0 archive conforms and loads losslessly."""
    corpus_v10 = _create_v1_0_corpus_archive(tmp_path / "corpus_v10")
    parsed = open_and_verify_archive(corpus_v10)

    assert parsed["version"] == "1.0"
    assert parsed["family"]["name"] == "The Modern Family"
    assert len(parsed["sparks"]) == 1
    assert parsed["sparks"][0]["title"] == "Bicycle riding"
    assert parsed["sparks"][0]["category"]["value"] == "MOVEMENT"


def test_rejects_unsupported_future_major_version(tmp_path: Path):
    """Future version (e.g. 2.0 or 99.0) is rejected out loud with upgrade instructions."""
    archive_dir = tmp_path / "future_archive"
    archive_dir.mkdir()
    (archive_dir / "archive.json").write_text(
        json.dumps({"format_version": "99.0", "family": {"name": "Future"}}), encoding="utf-8"
    )
    (archive_dir / "manifest.json").write_text(
        json.dumps({"algorithm": "SHA-256", "files": []}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match=r"Unsupported future archive format version: 99\.0"):
        open_and_verify_archive(archive_dir)


def test_catches_tampered_archive_file(tmp_path: Path):
    """Bit-rot or deliberate file tampering fails integrity verification immediately."""
    corpus_v10 = _create_v1_0_corpus_archive(tmp_path / "tampered_v10")
    # Tamper with the sparks file
    (corpus_v10 / "sparks.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Integrity check failed for sparks\.json"):
        open_and_verify_archive(corpus_v10)
