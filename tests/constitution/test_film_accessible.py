"""TASK-1209: Captions and audio descriptions by default (PRD 27, PRD 56).

Accessibility is a constitutional invariant:
1. Every compiled film generates closed caption cues and audio descriptions by default.
2. The grandmother who cannot hear or see clearly has equal dignity in viewing the film.
3. Captions never drift and audio descriptions accurately describe visual scenes.
"""

from __future__ import annotations

import pytest

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.domain.film import (
    AudioDescriptionCue,
    Citation,
    CitationKind,
    ConnectiveLine,
    Cue,
    FilmScene,
    FilmSpec,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.identity import FamilyId


@pytest.fixture
def sample_spec() -> FilmSpec:
    return FilmSpec(
        id="spec-accessible-1",
        family_id=FamilyId("fam-1"),
        title="Leo's Fourth Year",
        scenes=(
            FilmScene(
                id="scene-open",
                kind=SceneKind.OPENING,
                heading="Leo's Fourth Year",
                body="A collection of moments from 2026",
                voice=SceneVoice.synthetic(
                    line=ConnectiveLine.OPENING,
                    seconds=3.0,
                    media_id="synth-open",
                ),
            ),
            FilmScene(
                id="scene-bike",
                kind=SceneKind.SPARK,
                heading="Riding Without Stabilisers",
                body="First time in the sunlit green park",
                voice=SceneVoice.recorded(
                    text="Look at Leo riding without help on Sunday!",
                    seconds=4.0,
                    media_id="aud-bike",
                ),
                cites=(Citation(kind=CitationKind.MEDIA, id="aud-bike"),),
            ),
            FilmScene(
                id="scene-close",
                kind=SceneKind.CLOSING,
                heading="Everything here happened. Nothing here was invented.",
                voice=SceneVoice.silent(2.0),
            ),
        ),
    )


def test_compiled_film_generates_cues_and_audio_descriptions_by_default(sample_spec: FilmSpec):
    """Compiling any film produces timed captions and audio descriptions automatically."""
    compiler = FilmkitFilmCompiler()
    result = compiler.compile(sample_spec)
    assert result.is_ok(), f"Compilation failed: {result.unwrap_err()}"

    film = result.unwrap()

    # 1. Closed captions (Cues)
    assert len(film.cues) > 0
    for cue in film.cues:
        assert isinstance(cue, Cue)
        assert cue.start_seconds >= 0.0
        assert cue.end_seconds > cue.start_seconds
        assert len(cue.text.strip()) > 0

    # 2. Audio Descriptions
    assert len(film.audio_descriptions) == len(sample_spec.scenes)
    for desc in film.audio_descriptions:
        assert isinstance(desc, AudioDescriptionCue)
        assert desc.start_seconds >= 0.0
        assert desc.end_seconds > desc.start_seconds
        assert len(desc.description.strip()) > 0


def test_audio_descriptions_cover_every_visual_scene(sample_spec: FilmSpec):
    """Audio descriptions faithfully describe visual scene headings and bodies."""
    compiler = FilmkitFilmCompiler()
    film = compiler.compile(sample_spec).unwrap()

    desc_map = {d.description: d for d in film.audio_descriptions}

    # Opening scene description
    assert any("Leo's Fourth Year: A collection of moments from 2026" in d for d in desc_map)
    # Spark scene description
    assert any(
        "Riding Without Stabilisers: First time in the sunlit green park" in d for d in desc_map
    )
    # Closing scene description
    assert any("Everything here happened. Nothing here was invented." in d for d in desc_map)


def test_caption_timing_matches_voice_activity(sample_spec: FilmSpec):
    """Captions are timed to narration; silent scenes have no phantom captions."""
    compiler = FilmkitFilmCompiler()
    film = compiler.compile(sample_spec).unwrap()

    # Only scene-open (synthetic) and scene-bike (recorded) have speech
    assert len(film.cues) == 2

    # Verify speech texts
    texts = [cue.text for cue in film.cues]
    assert any("These are things that happened" in t for t in texts)
    assert any("Look at Leo riding without help" in t for t in texts)


def test_accessible_cues_and_descriptions_serialization(sample_spec: FilmSpec):
    """CompiledFilm.to_dict includes accessible cues and audio descriptions."""
    compiler = FilmkitFilmCompiler()
    film = compiler.compile(sample_spec).unwrap()

    payload = film.to_dict()
    assert "cues" in payload
    assert "audio_descriptions" in payload

    assert len(payload["cues"]) == len(film.cues)
    assert len(payload["audio_descriptions"]) == len(film.audio_descriptions)

    first_ad = payload["audio_descriptions"][0]
    assert "start_seconds" in first_ad
    assert "end_seconds" in first_ad
    assert "description" in first_ad
