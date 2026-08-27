"""Writing-system preparation happens before family bytes leave the archive."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from filmkit.process import run

from anuvritti.adapters.film.export import (
    RENDER_REQUIREMENTS_FILENAME,
    FilesystemFilmExporter,
    write_render_requirements,
)
from tests.support.archive import Archive

pytestmark = pytest.mark.integration


def test_compilation_derives_the_exact_world_bundle_without_copying_family_text(tmp_path: Path):
    archive = Archive()
    archive.moment("أول مرة نزل فيها وحده", on=date(2026, 3, 4))
    archive.moment("पहली बार वह अकेले फिसला", on=date(2026, 5, 19))
    package = archive.compile().unwrap()

    requirements_path = tmp_path / RENDER_REQUIREMENTS_FILENAME
    write_render_requirements(package, to=requirements_path).unwrap()
    requirements = json.loads(requirements_path.read_text())

    assert requirements["schema"] == "anuvritti.render-requirements.v1"
    assert requirements["scripts"] == ["Latin", "Arabic", "Devanagari"]
    assert requirements["world"]["package"] == "@anuvritti/world"
    assert requirements["world"]["version"] == "0.1.0"
    assert requirements["world"]["font_packages"] == {
        "@fontsource/ibm-plex-sans": "5.3.0",
        "@fontsource/newsreader": "5.3.0",
        "@fontsource/noto-naskh-arabic": "5.3.0",
        "@fontsource/noto-sans-arabic": "5.3.0",
        "@fontsource/noto-sans-devanagari": "5.3.0",
        "@fontsource/noto-serif-devanagari": "5.3.0",
    }
    receipt = requirements_path.read_text()
    assert "أول مرة" not in receipt
    assert "पहली बार" not in receipt
    assert not (tmp_path / "media").exists()
    checked = run(
        ["node", "packages/world/scripts/prepare-film.ts", str(requirements_path)],
        timeout=30,
        check=True,
    )
    assert "approved @anuvritti/world@0.1.0 for Latin, Arabic, Devanagari" in checked.stdout


def test_unsupported_text_names_the_scene_field_and_codepoint_before_export(tmp_path: Path):
    archive = Archive()
    archive.moment("first day at 家", on=date(2026, 3, 4), photo=archive.upload())

    error = archive.compile().unwrap_err()

    assert error.details["unsupported_text"] == [
        {
            "scene_id": "moment-mom-1",
            "field": "heading",
            "codepoints": ["U+5BB6"],
        }
    ]
    assert not (tmp_path / "FilmExport").exists()


def test_the_export_carries_the_same_requirements_that_can_be_sent_ahead(tmp_path: Path):
    archive = Archive()
    archive.moment("أول خطوة", on=date(2026, 3, 4), photo=archive.upload())
    package = archive.compile().unwrap()
    ahead = tmp_path / "ahead.json"
    write_render_requirements(package, to=ahead).unwrap()

    exported = (
        FilesystemFilmExporter(archive.media).export(package, into=tmp_path / "FilmExport").unwrap()
    )

    assert exported.requirements_path.read_bytes() == ahead.read_bytes()
    assert exported.requirements_path.name == RENDER_REQUIREMENTS_FILENAME
