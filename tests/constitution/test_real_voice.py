"""PRD 12, 39, 47 - the voice in a family's film is the family's voice.

PRD 39 puts voice cloning at research status and leaves it there. That is easy to honour on
the day it is written and hard to honour eighteen months later, when there is a title card
that would sound better spoken, a synthesiser costs a tenth of a cent, and nobody in the room
remembers that the line between "the machine reads the chapter headings" and "the machine
reads the memories" was ever meant to be load-bearing.

The failure this file exists for is not a bad film. It is a good one. A child at eighteen
hears a warm, unhurried voice say something true and gentle about a Tuesday in March, and no
one - not the child, not the parent, not the person who shipped it - can now say whether
anybody ever said it. The recording that would settle it does not exist, because there was
never a recording. There is no way back from that, which is why it has to be impossible
rather than discouraged.

So the rule is drawn in four places, and each is a different way of saying the same thing:

1. A machine may introduce a memory. It may never narrate one - `FilmScene` refuses.
2. A machine's entire vocabulary is four fixed sentences in `ConnectiveLine`, and there is
   no parameter anywhere through which a fifth could arrive.
3. Every voice heard in a film is a real file with a measured length. Nothing is estimated
   from the words, for a synthesiser any more than for a father.
4. Wherever a machine does speak, it is marked: in the compiled film, in the captions, and
   in the `film.json` that ships beside the media.

If one of these tests starts failing, the question is never how to make it pass.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import date
from pathlib import Path

import pytest

from anuvritti.adapters.film import filmkit_compiler
from anuvritti.adapters.film.export import FILM_FILENAME, FilesystemFilmExporter
from anuvritti.application import film as film_application
from anuvritti.application.film import ComposeFilmUseCase
from anuvritti.application.ports import Narrator
from anuvritti.domain import film as film_domain
from anuvritti.domain.film import (
    MACHINE_MARK,
    Citation,
    CitationKind,
    ConnectiveLine,
    FilmScene,
    NarrationOrigin,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import MediaId
from tests.support.archive import a_year
from tests.support.fakes import FakeNarrator

pytestmark = pytest.mark.constitution

#: The four sentences, written out here on purpose. This is a second, independent copy of the
#: machine's vocabulary: changing what a synthesiser may say now takes a deliberate edit to a
#: constitution test, which is exactly the amount of friction that decision deserves.
THE_WHOLE_VOCABULARY = {
    "OPENING": "These are things that happened.",
    "IN_THEIR_OWN_VOICE": "In their own voice.",
    "A_LITTLE_LATER": "A little later.",
    "CLOSING": "Everything here happened. Nothing here was invented.",
}


@pytest.fixture
def narrated():
    """A year with a synthesiser wired in - which is not how the product ships."""
    box = a_year()
    box.narrator = FakeNarrator(box.media)
    return box


@pytest.fixture
def silent_box():
    """A year with no narrator at all, which is how the product ships."""
    return a_year()


class TestOnlyAPersonNarratesAMemory:
    """The line between connective tissue and narration, drawn where scenes are built."""

    def test_a_machine_may_not_speak_over_a_scene_that_cites(self):
        with pytest.raises(ValueError, match="may not narrate one"):
            FilmScene(
                id="moment-mom-1",
                kind=SceneKind.VOICE,
                heading="the morning he let go of the fence",
                voice=SceneVoice.synthetic(
                    line=ConnectiveLine.A_LITTLE_LATER,
                    media_id=MediaId("med-tts"),
                    seconds=1.4,
                ),
                cites=(Citation(CitationKind.MOMENT, "mom-1"),),
            )

    def test_every_evidence_scene_in_a_real_film_is_a_person_or_silence(self, narrated):
        package = narrated.compile().unwrap()

        evidence = [scene for scene in package.film.scenes if scene.cites]
        assert evidence
        for scene in evidence:
            assert scene.voice.origin is not NarrationOrigin.SYNTHETIC, scene.id

    def test_only_the_cards_that_claim_nothing_are_spoken_by_a_machine(self, narrated):
        package = narrated.compile().unwrap()

        assert package.film.synthetic_scene_ids == ("opening", "closing")
        for scene in package.film.scenes:
            if scene.voice.is_synthetic:
                assert not scene.kind.is_evidence
                assert scene.cites == ()

    def test_an_unmeasured_recording_is_refused_rather_than_narrated_by_a_machine(self):
        """The tempting shortcut: the parent's audio has no length, so have the machine read
        the reflection instead. That produces a complete, plausible film with the father
        replaced, and nothing anywhere saying so."""
        box = a_year()
        box.narrator = FakeNarrator(box.media)
        orphan = box.upload(b"\x00\x00\x00\x20ftypM4A " + b"unmeasured" * 50, "audio/mp4")
        box.moment("he told the whole story to the dog", on=date(2026, 7, 2), audio=orphan)

        error = box.compile().unwrap_err()

        assert error.code is ErrorCode.FILM_NOT_COMPILABLE
        assert "will not guess how long a person spoke" in error.message


class TestTheMachineHasFourSentences:
    """A closed vocabulary is the only version of "neutral" that survives a deadline."""

    def test_the_whole_vocabulary_is_four_lines_and_this_is_them(self):
        assert {line.value: line.words for line in ConnectiveLine} == THE_WHOLE_VOCABULARY

    def test_no_line_has_anywhere_to_put_a_name_a_date_or_an_age(self):
        for line in ConnectiveLine:
            assert "{" not in line.words and "%" not in line.words, line.value
            assert not any(character.isdigit() for character in line.words), line.value

    def test_there_is_no_parameter_through_which_a_sentence_could_arrive(self):
        """The port takes a `ConnectiveLine`. Not a string with a rule about it - a type."""
        spoken = inspect.signature(SceneVoice.synthetic).parameters
        assert "text" not in spoken
        assert spoken["line"].annotation == "ConnectiveLine"

        speak = inspect.signature(Narrator.speak).parameters
        assert speak["line"].annotation == "ConnectiveLine"
        assert [name for name in speak if name not in {"self", "line", "family_id"}] == []

    def test_a_sentence_that_is_not_one_of_the_four_cannot_be_spoken(self):
        with pytest.raises(ValueError, match="says CLOSING exactly"):
            SceneVoice(
                NarrationOrigin.SYNTHETIC,
                2.0,
                text="Everything here happened, mostly.",
                media_id=MediaId("med-tts"),
                line=ConnectiveLine.CLOSING,
            )

    def test_a_recorded_voice_cannot_borrow_the_machines_lines(self):
        """A real recording tagged with a connective line would count as a person saying it."""
        with pytest.raises(ValueError, match="only a machine reads"):
            SceneVoice(
                NarrationOrigin.RECORDED,
                2.0,
                text=ConnectiveLine.CLOSING.words,
                media_id=MediaId("med-1"),
                line=ConnectiveLine.CLOSING,
            )


class TestMeasuredNeverEstimated:
    """The rule that already protects a father, applied to the machine without exception."""

    def test_every_voice_that_is_heard_is_a_file_that_travelled_with_the_film(self, narrated):
        package = narrated.compile().unwrap()

        heard = [scene.voice for scene in package.film.scenes if scene.voice.seconds > 0]
        assert len(heard) == 3  # the opening, the recording, the sign-off
        for voice in heard:
            assert voice.media_id is not None
            assert str(voice.media_id) in package.bundle.ids

    def test_a_synthetic_voice_without_a_file_has_no_length_to_report(self):
        with pytest.raises(ValueError, match="measured from the file"):
            SceneVoice(
                NarrationOrigin.SYNTHETIC,
                4.0,
                text=ConnectiveLine.OPENING.words,
                line=ConnectiveLine.OPENING,
            )

    def test_the_modules_that_decide_durations_contain_no_reading_pace(self):
        """A words-per-minute constant is how estimation gets in: it arrives as a fallback."""
        forbidden = ("wpm", "words_per_minute", "per_minute", "reading_speed")
        for module in (film_domain, film_application):
            source = Path(inspect.getfile(module)).read_text().lower()
            for word in forbidden:
                assert word not in source, f"{module.__name__} mentions {word}"

    def test_the_compilers_one_reading_pace_reaches_a_report_and_never_a_duration(self):
        """filmkit's `plan` prints "you asked for roughly this". Nothing else may see it."""
        tree = ast.parse(Path(inspect.getfile(filmkit_compiler)).read_text())
        uses = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id == "NOMINAL_WPM"
            and isinstance(node.ctx, ast.Load)
        ]
        assert len(uses) == 1
        keyword = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.keyword)
            and isinstance(node.value, ast.Name)
            and node.value.id == "NOMINAL_WPM"
        )
        assert keyword.arg == "target_wpm"

    def test_a_synthesiser_that_is_not_there_leaves_silence_rather_than_a_guess(self):
        box = a_year()
        box.narrator = FakeNarrator(box.media, failing=frozenset({"OPENING"}))

        package = box.compile().unwrap()

        opening = package.film.scenes[0]
        assert opening.id == "opening"
        assert opening.voice.origin is NarrationOrigin.SILENT
        assert opening.voice.seconds == 0.0
        assert package.film.synthetic_scene_ids == ("closing",)


class TestMarkedWhereverItAppears:
    """PRD 47's real requirement: a parent never learns this by hearing it."""

    def test_the_compiled_film_says_which_scenes_a_machine_spoke_and_which_lines(self, narrated):
        narration = narrated.compile().unwrap().film.narration

        assert narration["synthetic_scenes"] == ["opening", "closing"]
        assert narration["synthetic_lines"] == ["CLOSING", "OPENING"]
        assert 0.0 < narration["real_voice_share"] < 1.0
        assert narration["recorded_seconds"] == pytest.approx(6.2)

    def test_a_parent_is_told_in_words_before_they_press_play(self, narrated):
        notes = narrated.compile().unwrap().film.notes
        assert any("not a real voice" in note for note in notes)

    def test_a_machines_caption_carries_its_mark_into_the_picture(self, narrated):
        package = narrated.compile().unwrap()

        spoken = [cue.text for cue in package.film.cues if ConnectiveLine.CLOSING.words in cue.text]
        assert spoken
        assert all(MACHINE_MARK in text for text in spoken)

    def test_the_parents_own_words_are_never_marked_as_a_machines(self, silent_box):
        package = silent_box.compile().unwrap()
        for scene in package.film.scenes:
            assert MACHINE_MARK not in scene.voice.caption

    def test_the_film_that_ships_carries_the_accounting_beside_the_media(self, narrated, tmp_path):
        package = narrated.compile().unwrap()
        FilesystemFilmExporter(media=narrated.media).export(package, into=tmp_path).unwrap()

        shipped = json.loads((tmp_path / FILM_FILENAME).read_text())["film"]

        assert shipped["narration"]["synthetic_scenes"] == ["opening", "closing"]
        assert shipped["narration"]["real_voice_share"] < 1.0
        opening = next(s for s in shipped["scenes"] if s["id"] == "opening")
        assert opening["voice"]["read_by_a_machine"] is True
        assert opening["voice"]["line"] == "OPENING"


class TestWhatTheProductActuallyShips:
    """Every test above describes a film with a synthesiser in it. This is the default."""

    def test_no_narrator_is_wired_unless_somebody_wires_one(self):
        assert inspect.signature(ComposeFilmUseCase.__init__).parameters["narrator"].default is None

    def test_a_film_composed_the_shipped_way_is_a_person_or_nothing(self, silent_box):
        package = silent_box.compile().unwrap()

        assert package.film.real_voice_share == 1.0
        assert package.film.synthetic_scene_ids == ()
        assert package.film.narration["synthetic_lines"] == []
        # It may well carry a note about running short of the target. What it may never carry
        # is a note about a voice, because there is nothing to confess.
        assert not any("voice" in note for note in package.film.notes)
