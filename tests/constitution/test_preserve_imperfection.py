"""TASK-606 - no recording is ever rejected, trimmed or re-recorded (PRD 24).

    "Anuvritti should not create a polished highlight reel. Real family memories include
    burnt pancakes, failed science experiments, crying during bicycle practice... Often
    these become the memories people treasure."

PRD 24 is written about content, and it is really about *engineering*, because the ways a
system quietly polishes a recording are all small and all reasonable-looking:

* a minimum duration, so a stray tap does not create an empty note;
* a silence trim, so the file is smaller;
* a loudness normalisation, so playback is even;
* a "re-record" button, so the parent can do a better take;
* discarding the audio once a transcript exists, so the archive is cheaper.

Every one of those is a sensible engineering decision and every one of them destroys the
thing the product exists to keep. So this file checks for them structurally, at the level
where they would actually be written, rather than trusting that nobody will have the idea.

The one distinction worth stating out loud, because it looks like an exception and is not:
the *gesture* may have a threshold - a hold-to-talk that arms after 200ms so that a tap
never starts a recording at all. That filters an input, not a recording. Once audio exists
it is kept, whatever is on it and however long it lasts.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import anuvritti

SOURCE_ROOT = Path(anuvritti.__file__).parent
REPO_ROOT = SOURCE_ROOT.parents[1]
APP_SOURCE = REPO_ROOT / "apps" / "anuvritti" / "src"
CLIENT_SOURCE = REPO_ROOT / "packages" / "client" / "src"

PYTHON_FILES = sorted(SOURCE_ROOT.rglob("*.py"))
TS_FILES = sorted(
    p
    for root in (APP_SOURCE, CLIENT_SOURCE)
    for p in root.rglob("*.ts*")
    if "node_modules" not in p.parts
)

#: A constant with any of these names is a floor under what counts as a recording.
#:
#: Matched as a *prefix* rather than a whole word, because `MIN_RECORDING_SECONDS` is the
#: name someone would actually reach for and `\bMIN_RECORDING\b` sails straight past it -
#: an underscore is a word character. Case is not ignored: `min_years` and
#: `min_days_before_return` are real fields about a child's age and the Return Engine, and
#: neither is a floor under a recording.
FLOOR_NAMES = re.compile(
    r"\b(?:MIN|MINIMUM)_(?:DURATION|SECONDS|RECORDING|LENGTH|CLIP|AUDIO)\w*"
    r"|\b(?:min|minimum)(?:Duration|Seconds|Recording|Length|Clip|Audio)\w*"
    r"|\bTOO_SHORT\w*|\b(?:is|was)?[Tt]ooShort\w*"
)

#: The polishing verbs, in the shapes they would be written in.
POLISHING = re.compile(
    r"\b(trimSilence|trim_silence|normaliseLoudness|normalizeLoudness|normalise_audio"
    r"|normalize_audio|denoise|noiseSuppress|noise_suppress|autoGain|auto_gain"
    r"|reRecord|re_record|retake|redoRecording)\b"
)

#: Words that would be on a button offering to do the take again, or to throw one away.
#: `discard` is included: a recording that exists and is discarded is the whole failure.
RETAKE_WORDS = re.compile(
    r"\b(re-?record|record again|try again|retake|another take|start over|discard"
    r"|delete recording|too short|say more|speak up|hold longer)\b",
    re.IGNORECASE,
)


def _quoted_strings(source: str) -> list[str]:
    """Every double-quoted literal of four characters or more. Good enough for copy."""
    return [m.group(1) for m in re.finditer(r'"([^"\\\n]{4,})"', source)]


class TestNothingIsRejectedForBeingShort:
    @pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda p: p.stem)
    def test_no_python_module_names_a_minimum(self, path: Path):
        found = FLOOR_NAMES.findall(path.read_text())
        assert not found, f"{path.name} defines a floor under what counts as a recording: {found}"

    @pytest.mark.parametrize("path", TS_FILES, ids=lambda p: p.stem)
    def test_no_client_or_app_module_names_a_minimum(self, path: Path):
        found = FLOOR_NAMES.findall(path.read_text())
        assert not found, f"{path.name} defines a floor: {found}"

    @pytest.mark.parametrize("path", PYTHON_FILES, ids=lambda p: p.stem)
    def test_no_duration_is_compared_against_a_positive_floor(self, path: Path):
        """The comparison, not just the constant.

        `duration < 0.5` is the same rule written inline, and a name scan would sail past
        it. `duration > MAX_DURATION_SECONDS` is fine and must stay fine: that is a ceiling
        on what one request may claim, not a judgement about a short recording.
        """
        offenders = [
            ast.unparse(node)
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Compare) and _is_a_floor(node)
        ]
        assert not offenders, f"{path.name} rejects short recordings: {offenders}"

    def test_the_wire_schema_has_no_minimum_on_a_duration(self):
        """A Pydantic `gt=0.5` would be the whole constitution undone by a validator."""
        from anuvritti.interfaces.http.schemas import KeepVoiceNoteRequest

        field = KeepVoiceNoteRequest.model_fields["duration_seconds"]
        constraints = {type(m).__name__ for m in field.metadata}
        assert not constraints & {"Gt", "Ge"}, f"a floor reached the wire schema: {constraints}"

    def test_the_contract_says_so_out_loud(self):
        """A future reader of the API should not have to infer this from the absence.

        Read from the parsed document rather than the raw text, because YAML folds a long
        description across lines and an assertion against the file would be an assertion
        about where the line wraps.
        """
        import yaml

        spec = yaml.safe_load((REPO_ROOT / "docs" / "contracts" / "openapi.yaml").read_text())
        described = spec["paths"]["/voice"]["post"]["description"]
        assert "no minimum duration and there never will be" in described


class TestNothingIsPolished:
    @pytest.mark.parametrize("path", PYTHON_FILES + TS_FILES, ids=lambda p: p.stem)
    def test_nothing_trims_normalises_or_denoises(self, path: Path):
        found = POLISHING.findall(path.read_text())
        assert not found, (
            f"{path.name} improves a recording: {found}. Stumbles, laughter, imperfect "
            "grammar and background noise are part of the person (PRD 21)."
        )

    @pytest.mark.parametrize("path", TS_FILES, ids=lambda p: p.stem)
    def test_nothing_offers_to_do_the_take_again(self, path: Path):
        offenders = [s for s in _quoted_strings(path.read_text()) if RETAKE_WORDS.search(s)]
        assert not offenders, (
            f"{path.name} asks a parent to record their own voice better: {offenders}"
        )


class TestATranscriptNeverReplacesTheRecording:
    def test_attaching_a_transcript_cannot_reach_the_audio(self):
        """Checked by signature: `indexed_by` takes a transcript and nothing else.

        There is no media store, no path and no id in scope, so the method physically
        cannot delete, shorten or replace the bytes it is describing.
        """
        import inspect

        from anuvritti.domain.voice import VoiceNote

        assert set(inspect.signature(VoiceNote.indexed_by).parameters) == {"self", "transcript"}
        assert set(inspect.signature(VoiceNote.corrected_to).parameters) == {
            "self",
            "text",
            "at",
        }

    def test_a_voice_note_cannot_exist_without_its_media_id(self):
        """The schema-level version of the same rule.

        `voice_note.media_id` is the primary key, so there is no row that can hold words
        whose audio has gone - which is the artefact PRD 24 is really guarding against: a
        tidy paraphrase standing in for something a person actually said.
        """
        from anuvritti.adapters.persistence import schema

        source = Path(schema.__file__).read_text()
        assert "media_id              TEXT PRIMARY KEY" in source

    def test_no_code_path_deletes_media_when_a_transcript_arrives(self):
        from anuvritti.application import voice

        source = Path(voice.__file__).read_text()
        for verb in ("delete", "remove", "unlink", "discard"):
            assert verb not in source, f"application/voice.py {verb}s something"


class TestTheGestureMayFilterButTheRecordingMayNot:
    """The distinction that looks like an exception and is not."""

    def test_a_tap_is_filtered_before_any_audio_exists(self):
        recording = (APP_SOURCE / "voice" / "recording.ts").read_text()
        assert "ARMING_MS" in recording, "hold-to-talk has no arming threshold at all"

    def test_release_always_saves_whatever_was_captured(self):
        recording = Path(APP_SOURCE / "voice" / "recording.ts").read_text()
        assert re.search(r"\bkeep\b", recording), "the state machine has no keep step"
        assert not FLOOR_NAMES.search(recording)


class TestTheseChecksActuallyFire:
    """A constitution test that cannot fail is decoration."""

    @pytest.mark.parametrize(
        "sample",
        [
            "MIN_DURATION = 0.5",
            "const minDuration = 500;",
            "if (tooShort) return;",
            "MIN_RECORDING_SECONDS: Final = 1.0",
            "const minClipSeconds = 1;",
            "if (isTooShort(clip)) return;",
        ],
    )
    def test_the_floor_scan_catches_a_floor(self, sample):
        assert FLOOR_NAMES.search(sample)

    @pytest.mark.parametrize(
        "sample",
        [
            "MAX_DURATION_SECONDS = 14400",
            "duration_seconds: float",
            "durationMillis",
            # Two real fields elsewhere in this codebase that a careless pattern would eat.
            "min_years: int",
            "min_days_before_return=1",
        ],
    )
    def test_the_floor_scan_leaves_a_ceiling_alone(self, sample):
        assert not FLOOR_NAMES.search(sample)

    @pytest.mark.parametrize(
        "sample,rejected",
        [
            ("duration < 0.5", True),
            ("duration_seconds <= 1", True),
            ("0.5 > duration", True),
            ("duration_seconds < 0", False),
            ("duration_seconds > MAX_DURATION_SECONDS", False),
            ("len(text) < 4", False),
        ],
    )
    def test_the_comparison_scan_tells_a_floor_from_a_ceiling(self, sample, rejected):
        node = ast.parse(sample, mode="eval").body
        assert isinstance(node, ast.Compare)
        assert _is_a_floor(node) is rejected

    @pytest.mark.parametrize(
        "sample",
        ["Too short — try again", "Re-record", "Hold longer", "Discard this one", "Retake"],
    )
    def test_the_retake_scan_catches_a_retake(self, sample):
        assert RETAKE_WORDS.search(sample)

    @pytest.mark.parametrize("sample", ["Saved.", "That's in this year's film.", "Play"])
    def test_the_retake_scan_leaves_the_real_copy_alone(self, sample):
        assert not RETAKE_WORDS.search(sample)

    def test_the_string_scanner_finds_strings(self):
        assert _quoted_strings('const a = "Re-record"; const b = "ok";') == ["Re-record"]


def _is_a_floor(node: ast.Compare) -> bool:
    """Whether this comparison rejects a duration for being too small.

    Reads both directions - `duration < 0.5` and `0.5 > duration` - and treats zero as not
    a floor, because "shorter than no time at all" is an arithmetic accident rather than a
    short recording.
    """
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    left, right = node.left, node.comparators[0]
    op = node.ops[0]

    def mentions_duration(side: ast.expr) -> bool:
        return "duration" in ast.unparse(side).lower()

    def positive_number(side: ast.expr) -> bool:
        return (
            isinstance(side, ast.Constant)
            and isinstance(side.value, int | float)
            and (side.value > 0)
        )

    if mentions_duration(left) and positive_number(right):
        return isinstance(op, ast.Lt | ast.LtE)
    if mentions_duration(right) and positive_number(left):
        return isinstance(op, ast.Gt | ast.GtE)
    return False
