"""TASK-704 - the film compiler port, and the one adapter that satisfies it (PRD 34).

Three groups of tests, and they are not the same kind of test.

`TestTheFilmVocabulary` checks invariants that live in the types: a recorded voice that has no
file, a scene whose audio outlasts its picture. These fail at construction, in the domain, with
no compiler involved.

`TestCompiling` checks the arithmetic - where scenes land, when captions appear, what runs long.

`TestChromiumAndFfmpegStayOffTheFamilysBox` is the structural one, and it is the reason this
task exists. It reads the compiler's own source and the composition root's import graph, so it
fails on the commit that adds a browser to the family's server rather than on the day someone
notices the box is hot.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

import pytest

import anuvritti
from anuvritti.adapters.film import filmkit_compiler
from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.ports import FilmCompiler
from anuvritti.domain.film import (
    Citation,
    CitationKind,
    CompiledFilm,
    CompiledScene,
    ConnectiveLine,
    FilmScene,
    FilmSpec,
    NarrationOrigin,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MediaId

FAMILY = FamilyId("fam-1")
CHILD = ChildId("child-1")


def voice_note(seconds: float, text: str = "You said it back to me.") -> SceneVoice:
    return SceneVoice.recorded(media_id=MediaId("med-1"), seconds=seconds, text=text)


def scene(
    scene_id: str = "s1",
    *,
    kind: SceneKind = SceneKind.VOICE,
    seconds: float = 4.0,
    **overrides: object,
) -> FilmScene:
    fields: dict[str, object] = {
        "id": scene_id,
        "kind": kind,
        "heading": "The day he said it back",
        "voice": voice_note(seconds),
        "cites": (Citation(CitationKind.VOICE_NOTE, "vn-1"),),
    }
    fields.update(overrides)
    return FilmScene(**fields)  # type: ignore[arg-type]


def film(*scenes: FilmScene, **overrides: object) -> FilmSpec:
    fields: dict[str, object] = {
        "id": "film-2026",
        "family_id": FAMILY,
        "child_id": CHILD,
        "title": "The Year He Was Three",
        "scenes": scenes or (scene(),),
        "target_seconds": 60.0,
    }
    fields.update(overrides)
    return FilmSpec(**fields)  # type: ignore[arg-type]


class TestTheFilmVocabulary:
    def test_a_recorded_voice_without_a_file_is_not_a_recording(self):
        with pytest.raises(ValueError, match="nothing to play"):
            SceneVoice(NarrationOrigin.RECORDED, 3.0, text="he said this")

    def test_a_machine_may_not_say_a_sentence_of_its_own(self):
        """The failure mode this type exists for: a plausible line nobody ever spoke."""
        with pytest.raises(ValueError, match="connective lines"):
            SceneVoice(
                NarrationOrigin.SYNTHETIC,
                3.0,
                text="In March, he turned three.",
                media_id=MediaId("med-tts"),
            )

    def test_a_synthetic_voice_without_a_file_has_no_measured_length(self):
        with pytest.raises(ValueError, match="measured from the file"):
            SceneVoice(
                NarrationOrigin.SYNTHETIC,
                3.0,
                text=ConnectiveLine.CLOSING.words,
                line=ConnectiveLine.CLOSING,
            )

    def test_silence_may_not_smuggle_words_in(self):
        with pytest.raises(ValueError, match="may not carry words"):
            SceneVoice(NarrationOrigin.SILENT, 3.0, text="but he did say this")

    def test_a_voice_cannot_last_a_negative_length_of_time(self):
        with pytest.raises(ValueError, match="cannot last"):
            SceneVoice.silent(-1.0)

    def test_a_citation_needs_something_to_point_at(self):
        with pytest.raises(ValueError, match="cites nothing"):
            Citation(CitationKind.SPARK, "   ")

    def test_padding_is_silence_and_there_is_no_negative_silence(self):
        with pytest.raises(ValueError, match="negative silence"):
            scene(tail_seconds=-0.1)

    def test_a_scene_without_an_id_has_nowhere_to_hang_a_citation(self):
        with pytest.raises(ValueError, match="needs an id"):
            scene("   ")

    def test_a_floor_cannot_be_negative(self):
        with pytest.raises(ValueError, match="min_seconds cannot be negative"):
            scene(min_seconds=-1.0)

    def test_a_cap_below_the_floor_is_not_a_cap(self):
        with pytest.raises(ValueError, match="below min_seconds"):
            scene(min_seconds=10.0, max_seconds=4.0)

    def test_a_compiled_scene_cannot_hold_audio_that_would_be_cut_off(self):
        """The invariant that makes truncation unrepresentable rather than merely unlikely."""
        with pytest.raises(ValueError, match="cut off"):
            CompiledScene(
                id="s1",
                kind=SceneKind.VOICE,
                start_seconds=0.0,
                visual_seconds=3.0,
                voice=voice_note(9.0),
            )

    def test_a_film_with_no_voice_at_all_is_wholly_real(self):
        """Division by zero would be the obvious bug here, and 0.0 would be a slander."""
        silent = CompiledFilm(
            spec_id="f",
            title="t",
            scenes=(
                CompiledScene(
                    id="s1",
                    kind=SceneKind.OPENING,
                    start_seconds=0.0,
                    visual_seconds=3.0,
                    voice=SceneVoice.silent(0.0),
                ),
            ),
        )
        assert silent.real_voice_share == 1.0

    def test_a_scene_knows_what_it_cited(self):
        assert scene().cited_ids == frozenset({"vn-1"})


class TestTheContract:
    def test_the_port_is_a_runtime_checkable_protocol(self):
        assert getattr(FilmCompiler, "_is_runtime_protocol", False)

    def test_the_adapter_satisfies_it(self):
        assert isinstance(FilmkitFilmCompiler(), FilmCompiler)

    def test_the_port_offers_no_way_to_ask_for_a_video(self):
        """PRD 34's separation, asserted on the interface itself.

        A `render`, an `output_path` or a `codec` on this protocol would be the first step
        towards a browser on the family's box, and it would arrive as a helpful convenience.
        """
        surface = {name for name in dir(FilmCompiler) if not name.startswith("_")}
        assert surface == {"compile"}


class TestCompiling:
    def setup_method(self):
        self.compiler = FilmkitFilmCompiler()

    def test_a_scene_holds_for_its_measured_audio_plus_its_padding(self):
        compiled = self.compiler.compile(film(scene(seconds=4.0))).unwrap()
        only = compiled.scenes[0]
        assert only.audio_seconds == 4.0
        assert only.visual_seconds == pytest.approx(4.0 + 0.35 + 0.55)
        assert only.padding_seconds == pytest.approx(0.9)

    def test_scenes_are_laid_end_to_end(self):
        compiled = self.compiler.compile(
            film(scene("s1", seconds=2.0), scene("s2", seconds=3.0))
        ).unwrap()
        first, second = compiled.scenes
        assert first.start_seconds == 0.0
        assert second.start_seconds == pytest.approx(first.end_seconds)
        assert compiled.duration_seconds == pytest.approx(2.0 + 3.0 + 2 * 0.9)

    def test_a_floor_can_hold_a_scene_open_longer_than_its_voice(self):
        compiled = self.compiler.compile(film(scene(seconds=1.0, min_seconds=6.0))).unwrap()
        assert compiled.scenes[0].visual_seconds == pytest.approx(6.0)

    def test_the_length_never_comes_from_the_word_count(self):
        """Same words, four times the audio. A compiler that estimated would tie these."""
        words = "a b c d e f g h i j"
        quick = self.compiler.compile(
            film(scene(seconds=1.0, voice=voice_note(1.0, words)))
        ).unwrap()
        slow = self.compiler.compile(
            film(scene(seconds=4.0, voice=voice_note(4.0, words)))
        ).unwrap()
        assert slow.duration_seconds - quick.duration_seconds == pytest.approx(3.0)

    def test_captions_come_from_the_narration_and_sit_inside_the_silence(self):
        compiled = self.compiler.compile(film(scene(seconds=4.0))).unwrap()
        (cue,) = compiled.cues
        assert cue.text == "You said it back to me."
        assert cue.start_seconds == pytest.approx(0.45)
        assert cue.end_seconds == pytest.approx(4.45)

    def test_a_silent_scene_gets_no_caption(self):
        compiled = self.compiler.compile(
            film(scene("s1", voice=SceneVoice.silent(3.0)), scene("s2", seconds=2.0))
        ).unwrap()
        assert [cue.text for cue in compiled.cues] == ["You said it back to me."]

    def test_citations_survive_into_the_compiled_film_and_its_timeline(self):
        compiled = self.compiler.compile(film(scene())).unwrap()
        assert compiled.citations == (Citation(CitationKind.VOICE_NOTE, "vn-1"),)
        assert compiled.timeline["scenes"][0]["cites"] == [{"kind": "VOICE_NOTE", "id": "vn-1"}]

    def test_a_film_of_real_voices_scores_one_and_says_nothing(self):
        """No notes is the good outcome: nothing invented, nothing out of length."""
        compiled = self.compiler.compile(film(scene(seconds=4.0), target_seconds=4.9)).unwrap()
        assert compiled.real_voice_share == 1.0
        assert compiled.notes == ()

    def test_synthetic_narration_is_always_reported(self):
        """PRD 47. The one thing a parent must not learn by hearing it."""
        compiled = self.compiler.compile(
            film(
                scene("s1", seconds=3.0),
                scene(
                    "s2",
                    kind=SceneKind.CLOSING,
                    cites=(),
                    voice=SceneVoice.synthetic(
                        line=ConnectiveLine.CLOSING, media_id=MediaId("med-tts"), seconds=1.0
                    ),
                ),
            )
        ).unwrap()
        assert compiled.real_voice_share == pytest.approx(0.75)
        assert any("synthetic" in note for note in compiled.notes)

    def test_running_long_is_a_note_and_not_a_refusal(self):
        """A year that had a lot in it is not a compile error."""
        compiled = self.compiler.compile(
            film(scene(seconds=30.0), target_seconds=5.0, tolerance_seconds=1.0)
        ).unwrap()
        assert compiled.timing["status"] == "TIMING CONFLICT"
        assert any("target" in note for note in compiled.notes)

    def test_the_timing_report_measures_rather_than_predicts(self):
        compiled = self.compiler.compile(film(scene(seconds=4.0))).unwrap()
        assert compiled.timing["actual_duration_sec"] == pytest.approx(4.9)

    def test_a_film_with_no_scenes_is_not_a_film(self):
        error = self.compiler.compile(film(scenes=())).unwrap_err()
        assert error.code is ErrorCode.FILM_NOT_COMPILABLE
        assert "no scenes" in error.message

    def test_a_scene_id_used_twice_is_refused(self):
        error = self.compiler.compile(film(scene("s1"), scene("s1"))).unwrap_err()
        assert error.code is ErrorCode.FILM_NOT_COMPILABLE
        assert error.details["scene_id"] == "s1"

    def test_a_recording_longer_than_its_cap_is_refused_not_trimmed(self):
        error = self.compiler.compile(film(scene(seconds=20.0, max_seconds=8.0))).unwrap_err()
        assert error.code is ErrorCode.FILM_NOT_COMPILABLE
        assert "cut someone off" in error.message
        assert error.details["needs_seconds"] == pytest.approx(20.9)

    def test_a_cap_it_fits_inside_changes_nothing(self):
        compiled = self.compiler.compile(film(scene(seconds=4.0, max_seconds=8.0))).unwrap()
        assert compiled.duration_seconds == pytest.approx(4.9)

    def test_the_film_renders_to_a_dict_a_person_could_read(self):
        payload = self.compiler.compile(film(scene(seconds=4.0))).unwrap().to_dict()
        assert payload["title"] == "The Year He Was Three"
        assert payload["real_voice_share"] == 1.0
        assert payload["scenes"][0]["voice"]["origin"] == "RECORDED"


#: The four filmkit modules that decide things without needing anything installed. A whitelist
#: rather than a blacklist on purpose: a list of forbidden names goes stale the moment filmkit
#: grows a fifth expensive module, and nobody notices until the box is hot.
PERMITTED_FILMKIT_MODULES = frozenset(
    {"filmkit.captions", "filmkit.narration", "filmkit.timeline", "filmkit.timing"}
)

SOURCE_ROOT = Path(anuvritti.__file__).parent
CONTAINER = SOURCE_ROOT / "interfaces" / "http" / "container.py"


def _imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _reachable_from(start: Path) -> set[str]:
    by_name: dict[str, Path] = {}
    for path in SOURCE_ROOT.rglob("*.py"):
        parts = list(path.relative_to(SOURCE_ROOT.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        by_name[".".join(parts)] = path

    seen: set[str] = set()
    queue = deque([start])
    while queue:
        for imported in _imports_of(queue.popleft()):
            path = by_name.get(imported)
            if path is not None and imported not in seen:
                seen.add(imported)
                queue.append(path)
    return seen


class TestChromiumAndFfmpegStayOffTheFamilysBox:
    def test_the_compiler_imports_only_filmkits_weightless_half(self):
        offenders = {
            imported
            for imported in _imports_of(Path(filmkit_compiler.__file__))
            if imported.split(".")[0] == "filmkit" and imported not in PERMITTED_FILMKIT_MODULES
        }
        assert not offenders, (
            f"{sorted(offenders)} pulls a browser or an encoder into the compiler. "
            "Whatever draws the film consumes a CompiledFilm; it does not live here."
        )

    def test_the_compiler_never_names_a_renderer(self):
        source = Path(filmkit_compiler.__file__).read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        body = code.split('"""', 2)[-1]
        for banned in (
            "ChromiumPainter",
            "FrameFarm",
            "render_scene",
            "concat_scenes",
            "transcode_webm",
        ):
            assert banned not in body, f"{banned} has no business on the family's server"

    def test_the_family_server_never_reaches_the_film_package(self):
        """The composition root boots the always-on machine. It must not know this exists."""
        reachable = _reachable_from(CONTAINER)
        assert not {name for name in reachable if name.startswith("anuvritti.adapters.film")}

    def test_the_walk_is_actually_walking(self):
        """A closure that quietly returned nothing would pass the test above forever."""
        reachable = _reachable_from(CONTAINER)
        assert "anuvritti.application.ports" in reachable
        assert "anuvritti.adapters.persistence.sqlite" in reachable

    def test_the_import_check_would_notice(self, tmp_path: Path):
        sneaky = tmp_path / "sneaky.py"
        sneaky.write_text("from filmkit.compositor import render_scene\n")
        offenders = {
            imported
            for imported in _imports_of(sneaky)
            if imported.split(".")[0] == "filmkit" and imported not in PERMITTED_FILMKIT_MODULES
        }
        assert offenders == {"filmkit.compositor"}
