"""TASK-1304: FilmSpec Versioning & Compatibility Verification (PRD 8.6, PRD 8.7).

Verifies:
1. FilmSpec from older versions (v0.9/v1.0) compiles losslessly on today's compiler.
2. Unsupported future versions (e.g. 2.0, 99.0) are refused out loud with FILM_NOT_COMPILABLE.
3. A spec is never drawn differently in silence.
"""

from __future__ import annotations

import pytest

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.domain.film import (
    Citation,
    CitationKind,
    ConnectiveLine,
    FilmScene,
    FilmSpec,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId


@pytest.fixture
def base_scenes():
    return (
        FilmScene(
            id="sc-open",
            kind=SceneKind.OPENING,
            heading="A Year of Leo",
            body="From one to two",
            voice=SceneVoice.silent(2.5),
        ),
        FilmScene(
            id="sc-spark-1",
            kind=SceneKind.SPARK,
            heading="First Steps",
            body="Walking across the rug",
            voice=SceneVoice.recorded(
                media_id=MediaId("med-voice-1"), seconds=4.0, text="He did it!"
            ),
            cites=(Citation(CitationKind.SPARK, "spark-101"),),
        ),
        FilmScene(
            id="sc-closing",
            kind=SceneKind.CLOSING,
            heading="Our Family",
            body="Everything here happened. Nothing here was invented.",
            voice=SceneVoice.synthetic(
                line=ConnectiveLine.CLOSING,
                media_id=MediaId("med-synth-closing"),
                seconds=3.0,
            ),
        ),
    )


def test_spec_version_defaults_to_1_0(base_scenes):
    spec = FilmSpec(
        id="film-01",
        family_id=FamilyId("fam-01"),
        title="Leo Year One",
        scenes=base_scenes,
    )
    assert spec.spec_version == "1.0"
    data = spec.to_dict()
    assert data["spec_version"] == "1.0"
    assert data["id"] == "film-01"


def test_older_version_spec_compiles_on_todays_compiler(base_scenes):
    """v0.9 spec dictionary without spec_version or with legacy structure compiles cleanly."""
    legacy_dict = {
        "spec_version": "0.9",
        "id": "film-legacy-09",
        "family_id": "fam-01",
        "title": "Leo Year One",
        "scenes": [
            {
                "id": "sc-open",
                "kind": "OPENING",
                "heading": "Opening Scene",
                "voice": {"origin": "SILENT", "seconds": 2.0},
                "cites": [],
            },
            {
                "id": "sc-spark-1",
                "kind": "SPARK",
                "heading": "First Steps",
                "voice": {
                    "origin": "RECORDED",
                    "seconds": 3.5,
                    "text": "He walked!",
                    "media_id": "med-voice-1",
                },
                "cites": [{"kind": "SPARK", "id": "spark-101", "source_hash": "sha-spk"}],
            },
            {
                "id": "sc-close",
                "kind": "CLOSING",
                "heading": "The End",
                "voice": {"origin": "SILENT", "seconds": 2.0},
                "cites": [],
            },
        ],
    }

    parsed_res = FilmSpec.from_dict(legacy_dict)
    assert parsed_res.is_ok(), f"Failed to parse legacy spec: {parsed_res.unwrap_err()}"
    parsed_spec = parsed_res.unwrap()

    assert parsed_spec.spec_version == "0.9"
    assert len(parsed_spec.scenes) == 3

    # Compile with today's compiler
    compiler = FilmkitFilmCompiler()
    compiled_res = compiler.compile(parsed_spec)
    assert compiled_res.is_ok()
    compiled = compiled_res.unwrap()

    assert compiled.spec_id == "film-legacy-09"
    assert len(compiled.scenes) == 3
    assert compiled.duration_seconds > 0


def test_refuses_unsupported_future_version_out_loud():
    """Future spec version 2.0 is refused out loud, never silently misrendered."""
    future_dict = {
        "spec_version": "2.0",
        "id": "film-future-01",
        "family_id": "fam-01",
        "title": "Future Film",
        "scenes": [],
    }

    res = FilmSpec.from_dict(future_dict)
    assert res.is_err()
    err = res.unwrap_err()
    assert err.code == ErrorCode.FILM_NOT_COMPILABLE
    assert "unsupported future FilmSpec version '2.0'" in err.message


def test_refuses_malformed_spec_version():
    """Malformed version strings are refused immediately."""
    malformed_dict = {
        "spec_version": "invalid-version",
        "id": "film-malformed",
        "family_id": "fam-01",
        "title": "Malformed",
        "scenes": [],
    }

    res = FilmSpec.from_dict(malformed_dict)
    assert res.is_err()
    assert res.unwrap_err().code == ErrorCode.FILM_NOT_COMPILABLE


def test_round_trip_serialization_is_lossless(base_scenes):
    """to_dict -> from_dict preserves all scene properties, timing, and citations."""
    orig_spec = FilmSpec(
        id="film-roundtrip",
        family_id=FamilyId("fam-01"),
        title="Lossless Film",
        scenes=base_scenes,
    )

    data = orig_spec.to_dict()
    reconstructed_res = FilmSpec.from_dict(data)
    assert reconstructed_res.is_ok()
    reconstructed = reconstructed_res.unwrap()

    assert reconstructed.id == orig_spec.id
    assert reconstructed.family_id == orig_spec.family_id
    assert reconstructed.title == orig_spec.title
    assert reconstructed.spec_version == orig_spec.spec_version
    assert len(reconstructed.scenes) == len(orig_spec.scenes)

    for s_orig, s_recon in zip(orig_spec.scenes, reconstructed.scenes, strict=True):
        assert s_recon.id == s_orig.id
        assert s_recon.kind == s_orig.kind
        assert s_recon.heading == s_orig.heading
        assert s_recon.body == s_orig.body
        assert s_recon.voice.origin == s_orig.voice.origin
        assert s_recon.voice.seconds == s_orig.voice.seconds
        assert s_recon.voice.media_id == s_orig.voice.media_id
        assert s_recon.cites == s_orig.cites
