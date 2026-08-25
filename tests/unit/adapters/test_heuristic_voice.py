"""TASK-604 - speaking earns the same free categorisation that typing does (PRD 13, 48).

The claim this file has to defend is a comparison, not a threshold. It is easy to write an
intent test that passes by tuning a lexicon until one sentence lands where you wanted. The
interesting question is whether a parent who *speaks* ends up worse understood than one who
*types*, because if they do, voice becomes the expensive way to save something and the
whole of PRD 12 quietly stops being used.

So the centre of this file is `TestParity`: the same words, once typed and once spoken, and
the spoken reading may never be the weaker of the two.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.adapters.intent.spoken import (
    MAX_CONFIDENCE,
    VETOED_CONFIDENCE,
    SpokenIntentEngine,
    spoken_phrases,
)
from anuvritti.domain.values import IntentType, SourceKind, SourceRef

ENGINE = SpokenIntentEngine(HeuristicIntentEngine())
CAPTIONS = HeuristicIntentEngine()


def spoken(transcript: str) -> SourceRef:
    """A recording that has been indexed. The transcript rides in `source.text`."""
    return SourceRef.from_media(SourceKind.VOICE, media_id="med-1", text=transcript)


def heard(transcript: str) -> IntentType:
    return ENGINE.infer(spoken(transcript)).intent


class TestSentencesAParentActuallySays:
    """PRD 13's list, read back as the speech it plainly is."""

    @pytest.mark.parametrize(
        "said,meant",
        [
            ("I want to buy this for him", IntentType.BUY),
            ("we should get him one of these for his birthday", IntentType.BUY),
            ("I want to do this with him one weekend", IntentType.DO),
            ("let us try this together", IntentType.DO),
            ("I want him to watch this someday", IntentType.WATCH),
            ("show him this when he is older", IntentType.WATCH),
            ("I want to teach him this", IntentType.TEACH),
            ("he should learn to say sorry properly", IntentType.TEACH),
            ("read this to him at bedtime", IntentType.READ),
            ("I want to remember this", IntentType.REMEMBER),
            ("this reminds me of my childhood", IntentType.REMEMBER),
            ("note to self, he called the elevator an alligator", IntentType.REMEMBER),
        ],
    )
    def test_the_verb_is_the_signal(self, said, meant):
        assert heard(said) == meant

    def test_a_transcript_with_no_verb_in_it_is_still_kept_as_something_to_remember(self):
        """The honest default for someone recording their own voice."""
        assert heard("so this thing here, the blue one") is IntentType.REMEMBER

    def test_an_unindexed_recording_leaves_the_caption_engine_alone(self):
        """No transcript, nothing said. The base answer stands rather than a guess."""
        bare = SourceRef.from_media(SourceKind.VOICE, media_id="med-1")
        assert ENGINE.infer(bare).intent is IntentType.REMEMBER


class TestSpeechIsNotACaption:
    """The three things captions never do, each one a wrong answer without this layer."""

    def test_a_correction_mid_sentence_is_taken_as_the_correction(self):
        """ "I want to watch- no, actually I want to do this with him."

        The caption engine has no notion of order, so it sees `watch` and `do` and picks
        whichever the lexicon happened to weight higher. A sentence has an order, and the
        last thing said is the thing that was decided.
        """
        assert heard("I want him to watch this, no, actually I want to do this with him") is (
            IntentType.DO
        )

    def test_a_negated_intent_is_not_scored_as_that_intent(self):
        """The failure that is worse than no answer: reading the exact opposite."""
        assert CAPTIONS.infer(spoken("I do not want to buy him another one")).intent is (
            IntentType.BUY
        )
        assert heard("I do not want to buy him another one") is not IntentType.BUY

    def test_a_vetoed_reading_lands_on_remember_rather_than_on_nothing(self):
        """Refusing to add evidence is not enough - the caption's score is already there.

        The whole sentence still gets kept; it just gets kept as "I want to remember this",
        at a confidence that says the machine knows what was ruled out and not much else.
        """
        said = ENGINE.infer(spoken("I do not want to buy him another one"))
        assert said.intent is IntentType.REMEMBER
        assert said.intent_confidence == VETOED_CONFIDENCE

    def test_a_veto_does_not_fire_when_the_same_intent_is_affirmed_elsewhere(self):
        said = "I dont want to buy the big one, but I do want to buy the small one"
        assert heard(said) is IntentType.BUY

    def test_negation_is_scoped_to_its_clause(self):
        said = "I do not want to buy it, I want to do this with him instead"
        assert heard(said) is IntentType.DO

    def test_a_phrase_that_carries_its_own_negation_survives(self):
        """ "I don't want to forget this" is the most emphatic REMEMBER there is.

        Suppressing it because the clause contains "don't" would drop the one the parent
        meant most.
        """
        assert heard("I dont want to forget this") is IntentType.REMEMBER
        assert heard("I do not want to forget how he says it") is IntentType.REMEMBER

    def test_hesitation_does_not_make_a_parent_less_understood(self):
        fluent = ENGINE.infer(spoken("I want to teach him this"))
        hesitant = ENGINE.infer(spoken("um, so, I want to, uh, teach him this, you know"))
        assert hesitant.intent == fluent.intent
        assert hesitant.intent_confidence == fluent.intent_confidence

    def test_the_word_carrying_a_correction_is_never_deleted_as_filler(self):
        """ "actually" is a clause boundary, not a disfluency.

        Removing it would leave the layer reading the sentence the parent abandoned.
        """
        from anuvritti.adapters.intent.spoken import FILLERS

        assert "actually" not in FILLERS
        assert heard("we should buy it, actually let us make it with him") is IntentType.DO

    @pytest.mark.parametrize("contraction", ["dont", "don't", "don\u2019t"])
    def test_every_way_a_phone_transcribes_a_contraction_reads_the_same(self, contraction):
        """iOS and Android disagree about apostrophes; the parent said one thing."""
        assert heard(f"I {contraction} want to buy this") is not IntentType.BUY


class TestParity:
    """The claim TASK-604 actually makes. Speaking must not cost understanding."""

    #: The same content, once as a typed note on a link and once as a spoken transcript.
    SAME_WORDS: ClassVar[list[str]] = [
        "I want to buy this for him",
        "I want to do this with him this weekend",
        "I want him to watch this someday",
        "I want to teach him this",
        "read this to him at bedtime",
        "I want to remember this",
    ]

    @pytest.mark.parametrize("words", SAME_WORDS)
    def test_spoken_is_never_understood_worse_than_typed(self, words):
        typed = CAPTIONS.infer(SourceRef.from_text(words), note=words)
        said = ENGINE.infer(spoken(words))
        assert said.intent_confidence >= typed.intent_confidence, (
            f"speaking {words!r} was understood less confidently than typing it"
        )

    @pytest.mark.parametrize("words", SAME_WORDS)
    def test_spoken_reaches_a_real_intent_rather_than_falling_back(self, words):
        """Not merely "as good as typed" - actually understood.

        Parity with a caption engine that shrugs would be parity at zero.
        """
        said = ENGINE.infer(spoken(words))
        assert said.intent_confidence.value >= 0.5

    def test_the_category_a_transcript_earns_is_the_one_typing_would_have_earned(self):
        """Categorisation is free either way. Only the intent layer is speech-aware."""
        words = "I want to do this volcano experiment with him"
        assert ENGINE.infer(spoken(words)).category == CAPTIONS.infer(spoken(words)).category

    def test_an_age_stated_out_loud_is_read_the_same_as_one_written_down(self):
        said = ENGINE.infer(spoken("this looks perfect for ages 5-8"))
        assert said.age_range is not None
        assert (said.age_range.min_years, said.age_range.max_years) == (5, 8)


class TestItStaysAnInference:
    def test_nothing_spoken_ever_reaches_certainty(self):
        """PRD 8.7 - certainty belongs to the person, not to a reading of them."""
        for phrase in spoken_phrases():
            inferred = ENGINE.infer(spoken(f"{phrase} {phrase} {phrase}"))
            assert inferred.intent_confidence.value <= MAX_CONFIDENCE

    def test_a_caption_is_left_exactly_as_it_was(self):
        """The layer is a decorator. Nothing about the existing behaviour moves."""
        link = SourceRef.from_url(
            "https://instagram.com/reel/abc",
            creator="@sciencedad",
            title="Balloon rocket experiment for ages 5-8",
        )
        assert ENGINE.infer(link, note="lets try this") == CAPTIONS.infer(
            link, note="lets try this"
        )

    @pytest.mark.parametrize(
        "kind", [SourceKind.URL, SourceKind.TEXT, SourceKind.PHOTO, SourceKind.SCREENSHOT]
    )
    def test_only_a_recording_gets_the_spoken_layer(self, kind):
        source = (
            SourceRef.from_text("I want to buy this")
            if kind is SourceKind.TEXT
            else SourceRef.from_url("https://example.com/x", text="I want to buy this")
            if kind is SourceKind.URL
            else SourceRef.from_media(kind, media_id="med-1", text="I want to buy this")
        )
        assert ENGINE.infer(source) == CAPTIONS.infer(source)

    def test_it_is_deterministic(self):
        said = "I want to teach him this, and read it to him at bedtime"
        assert ENGINE.infer(spoken(said)) == ENGINE.infer(spoken(said))
