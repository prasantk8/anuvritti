"""`FilmCompiler`, implemented on filmkit's arithmetic (TASK-704).

filmkit is the film compiler pulled out of autovideo-engine, and it was pulled out in a
particular shape: everything expensive in it - the browser, the synthesiser, the shell - is a
port, so the parts that *decide* things need nothing installed to run. This adapter uses only
those parts.

That is not a coincidence to be grateful for; it is the reason the extraction was worth doing.
Four modules are imported here and a test enforces the list:

    filmkit.narration   what a track is, and how words are counted
    filmkit.timing      how long a scene holds, given its measured audio
    filmkit.timeline    where each scene sits, and what it cites
    filmkit.captions    when each caption appears

None of them opens a socket, spawns a process or draws a pixel. `filmkit.browser` and
`filmkit.compositor` - Chromium and FFmpeg - are not imported and must not be, because this
code runs wherever the family's archive lives. See `FilmCompiler` in the application ports.

One honest caveat: `import filmkit.narration` executes `filmkit/__init__.py`, which imports
`filmkit.process`, which imports `subprocess`. Nothing is spawned by that, but it means the
guarantee here is about what this module *names*, checked by reading its imports, rather than
about what ends up in `sys.modules`. The check that catches a real regression is the one that
fires when someone adds `from filmkit import render_scene` to this file.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from filmkit.captions import cues as caption_cues
from filmkit.narration import RECORDED, SYNTHETIC, count_words
from filmkit.narration import Narration as Track
from filmkit.timeline import FrameEntry, SceneEntry, Timeline
from filmkit.timing import BY_AUDIO, Beat, plan, visual_seconds

from anuvritti.adapters.film._world_font_policy import (
    COMMON_RANGES,
    SCRIPT_ORDER,
    SCRIPT_RANGES,
    WORLD_BUNDLE_NAME,
    WORLD_BUNDLE_VERSION,
    WORLD_FONT_PACKAGES,
)
from anuvritti.domain.film import (
    AudioDescriptionCue,
    CompiledFilm,
    CompiledScene,
    Cue,
    FilmScene,
    FilmSpec,
    NarrationOrigin,
)
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

#: A reading pace, used for one thing only: the "you asked for roughly this, you got that"
#: line in the timing report. It reaches no duration and no picture - `visual_seconds` takes a
#: beat and a measured number of seconds, and has no parameter it could arrive through. That
#: signature is asserted by a test in filmkit, which is what makes "measured never estimated"
#: a property of the code rather than a promise in a comment.
NOMINAL_WPM = 150.0

#: filmkit stamps a content hash on audio it produced itself. This compiler never opens the
#: bytes - a recording stays in the family's media store and is fetched by whatever draws the
#: film - so there is nothing here to hash, and saying so is better than inventing a digest.
NOT_HASHED_HERE = ""

_ORIGIN_TO_FILMKIT = {
    NarrationOrigin.RECORDED: RECORDED,
    NarrationOrigin.SYNTHETIC: SYNTHETIC,
    NarrationOrigin.SILENT: SYNTHETIC,
}


def _track(scene: FilmScene) -> Track:
    """The scene's audio, described for filmkit. `duration_sec` is the measurement."""
    voice = scene.voice
    return Track(
        scene_id=scene.id,
        voice=voice.origin.value.lower(),
        rate="+0%",
        pitch="+0Hz",
        text=voice.text,
        word_count=count_words(voice.text),
        duration_sec=voice.seconds,
        sha256=NOT_HASHED_HERE,
        path=str(voice.media_id) if voice.media_id else "",
        cache_key=scene.id,
        origin=_ORIGIN_TO_FILMKIT[voice.origin],
    )


def _beat(scene: FilmScene) -> Beat:
    return Beat(
        id=scene.id,
        type=scene.kind.value,
        mode=BY_AUDIO,
        min_sec=scene.min_seconds,
        lead_in_sec=scene.lead_in_seconds,
        tail_sec=scene.tail_seconds,
    )


class FilmkitFilmCompiler:
    """Places every scene, times every caption, and draws nothing.

    Compiling is arithmetic over durations. It is fast and it is free, which is the point: a
    parent can reorder a year, see what it now runs to, and change their mind, without a
    render ever happening. The render is a separate, heavier, elsewhere thing that consumes
    what this produces.
    """

    __slots__ = ()

    def compile(self, spec: FilmSpec) -> Result[CompiledFilm, DomainError]:
        refusal = _refuse(spec)
        if refusal is not None:
            return Err(refusal)
        requirements = _render_requirements(spec)
        if isinstance(requirements, DomainError):
            return Err(requirements)

        beats = [_beat(scene) for scene in spec.scenes]
        tracks = [_track(scene) for scene in spec.scenes]

        # One arithmetic, used everywhere. `plan` re-derives the same numbers for its report;
        # the picture is built from these, so the two can never round apart.
        holds = [
            visual_seconds(beat, scene.voice.seconds)
            for beat, scene in zip(beats, spec.scenes, strict=True)
        ]

        starts: list[float] = []
        cursor = 0.0
        for hold in holds:
            starts.append(cursor)
            cursor += hold

        timeline = Timeline(
            project=spec.id,
            fps=spec.fps,
            width=spec.width,
            height=spec.height,
            scenes=[
                SceneEntry(
                    id=scene.id,
                    type=scene.kind.value,
                    start_sec=start,
                    audio_path=str(scene.voice.media_id) if scene.voice.media_id else "",
                    audio_duration_sec=scene.voice.seconds,
                    visual_duration_sec=hold,
                    # One held state per scene. Whatever draws the film may subdivide it, and
                    # filmkit checks that subdivision against this number when it does.
                    frames=[
                        FrameEntry(
                            image=f"{scene.id}.png", duration_sec=hold, label=scene.kind.value
                        )
                    ],
                    # `caption`, not `text`: this field is what captions are cut from,
                    # and a machine's sentence carries its mark into the picture.
                    narration=scene.voice.caption,
                    shows=[part for part in (scene.heading, scene.body) if part],
                    cites=[citation.to_dict() for citation in scene.cites],
                )
                for scene, start, hold in zip(spec.scenes, starts, holds, strict=True)
            ],
        )

        report = plan(
            beats,
            tracks,
            target_wpm=NOMINAL_WPM,
            target_sec=spec.target_seconds,
            tolerance_sec=spec.tolerance_seconds,
        )

        compiled = tuple(
            CompiledScene(
                id=scene.id,
                kind=scene.kind,
                start_seconds=start,
                visual_seconds=hold,
                voice=scene.voice,
                cites=scene.cites,
            )
            for scene, start, hold in zip(spec.scenes, starts, holds, strict=True)
        )

        audio_desc_cues = tuple(
            AudioDescriptionCue(
                start_seconds=scene.start_seconds,
                end_seconds=scene.end_seconds,
                description=(
                    f"{spec_scene.heading}: {spec_scene.body}"
                    if spec_scene.body
                    else spec_scene.heading
                ),
            )
            for scene, spec_scene in zip(compiled, spec.scenes, strict=True)
            if spec_scene.heading
        )

        timeline_payload = timeline.to_json()
        timeline_payload["render_requirements"] = requirements
        film = CompiledFilm(
            spec_id=spec.id,
            title=spec.title,
            scenes=compiled,
            cues=tuple(
                Cue(start_seconds=start, end_seconds=end, text=text)
                for start, end, text in caption_cues(timeline)
                if text.strip()
            ),
            audio_descriptions=audio_desc_cues,
            timeline=timeline_payload,
            timing=report.to_json(),
            notes=(),
        )
        return Ok(_with_notes(film, report.conflict, spec.target_seconds))


def _refuse(spec: FilmSpec) -> DomainError | None:
    """The three ways a spec is not a film. Each names the scene, so it can be fixed."""
    if not spec.scenes:
        return DomainError(
            ErrorCode.FILM_NOT_COMPILABLE,
            "a film with no scenes is not a film",
            {"spec_id": spec.id},
        )

    seen: set[str] = set()
    for scene_id in spec.scene_ids:
        if scene_id in seen:
            return DomainError(
                ErrorCode.FILM_NOT_COMPILABLE,
                f"scene id {scene_id!r} appears twice, so its citations point at two places",
                {"spec_id": spec.id, "scene_id": scene_id},
            )
        seen.add(scene_id)

    for scene in spec.scenes:
        if scene.max_seconds is None:
            continue
        hold = visual_seconds(_beat(scene), scene.voice.seconds)
        if hold > scene.max_seconds:
            return DomainError(
                ErrorCode.FILM_NOT_COMPILABLE,
                f"{scene.id} needs {hold:.1f}s but is capped at {scene.max_seconds:.1f}s - "
                "shorten it or raise the cap, because trimming it would cut someone off",
                {
                    "spec_id": spec.id,
                    "scene_id": scene.id,
                    "needs_seconds": round(hold, 3),
                    "max_seconds": scene.max_seconds,
                },
            )
    return None


def _render_requirements(spec: FilmSpec) -> dict[str, Any] | DomainError:
    requested: set[str] = set()
    unsupported: list[dict[str, object]] = []
    for scene in spec.scenes:
        for field, text in (
            ("heading", scene.heading),
            ("body", scene.body),
            ("narration", scene.voice.caption),
        ):
            refused: set[int] = set()
            for character in unicodedata.normalize("NFC", text):
                codepoint = ord(character)
                category = unicodedata.category(character)
                if _in_ranges(codepoint, COMMON_RANGES) and category[0] not in {"L", "M"}:
                    continue
                script = next(
                    (name for name in SCRIPT_ORDER if _in_ranges(codepoint, SCRIPT_RANGES[name])),
                    None,
                )
                if script is None:
                    refused.add(codepoint)
                else:
                    requested.add(script)
            if refused:
                unsupported.append(
                    {
                        "scene_id": scene.id,
                        "field": field,
                        "codepoints": [_codepoint(value) for value in sorted(refused)],
                    }
                )
    if unsupported:
        first = unsupported[0]
        return DomainError(
            ErrorCode.FILM_NOT_COMPILABLE,
            f"{first['scene_id']}.{first['field']} uses text the approved world bundle "
            "cannot draw offline",
            {"spec_id": spec.id, "unsupported_text": unsupported},
        )
    return {
        "schema": "anuvritti.render-requirements.v1",
        "scripts": [name for name in SCRIPT_ORDER if name in requested],
        "world": {
            "package": WORLD_BUNDLE_NAME,
            "version": WORLD_BUNDLE_VERSION,
            "font_packages": dict(WORLD_FONT_PACKAGES),
        },
    }


def _in_ranges(codepoint: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(first <= codepoint <= last for first, last in ranges)


def _codepoint(value: int) -> str:
    return f"U+{value:04X}"


def _with_notes(film: CompiledFilm, over_target: bool, target_seconds: float) -> CompiledFilm:
    """Things a person should be told, none of which are failures.

    A year that runs long is not a bug - it is a year that had a lot in it, and refusing to
    compile it would be the compiler overruling the family about their own child. Synthetic
    narration is not a failure either, but it is the one thing a parent should never discover
    by hearing it.
    """
    notes: list[str] = []
    if over_target:
        notes.append(f"runs {film.duration_seconds:.0f}s against a target of {target_seconds:.0f}s")
    if film.synthetic_seconds > 0:
        spoken = film.recorded_seconds + film.synthetic_seconds
        notes.append(
            f"{film.synthetic_seconds:.0f}s of {spoken:.0f}s spoken is synthetic, not a real voice"
        )
    return CompiledFilm(
        spec_id=film.spec_id,
        title=film.title,
        scenes=film.scenes,
        cues=film.cues,
        audio_descriptions=film.audio_descriptions,
        timeline=film.timeline,
        timing=film.timing,
        notes=tuple(notes),
    )
