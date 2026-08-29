"""TASK-801 - the family's own lexicon (PRD 44, 13, 8.1).

The failure mode this guards is not a wrong guess. It is a product that learns from one
family and answers another with what it learned - which is the single thing PRD 44 says
this product will not do, and which is invisible from the outside because the answers only
get better.

So the tests here are mostly about what the lexicon refuses to know: another family's
words, its own guesses, a word said once, a word this family uses two ways, and anything at
all about which Spark taught it.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anuvritti.domain.lexicon import (
    MAX_TERMS,
    MAX_WEIGHT,
    MIN_EVIDENCE_TO_SPEAK,
    STOPWORDS,
    Correction,
    Evidence,
    FamilyLexicon,
    LexiconField,
    terms_in,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId

OURS = FamilyId("fam-ours")
THEIRS = FamilyId("fam-theirs")
T0 = datetime(2026, 3, 4, 19, 30, tzinfo=UTC)

LEXICON_SOURCE = Path("src/anuvritti/domain/lexicon.py").read_text(encoding="utf-8")


def correction(
    *,
    family_id: FamilyId = OURS,
    field: LexiconField = LexiconField.INTENT,
    to: str = "TEACH",
    at: datetime = T0,
    title: str | None = None,
    text: str | None = None,
    note: str | None = None,
) -> Correction:
    return Correction.from_override(
        family_id=family_id, field=field, corrected_to=to, at=at, title=title, text=text, note=note
    )


def made_up_word(index: int) -> str:
    """A distinct alphabetic nonsense word. `terms_in` reads letters only, so a counter
    has to be spelled rather than written."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return "zz" + "".join(letters[(index // 26**place) % 26] for place in (2, 1, 0))


def taught(lexicon: FamilyLexicon, *corrections: Correction) -> FamilyLexicon:
    for one in corrections:
        lexicon = lexicon.learn(one).unwrap()
    return lexicon


class TestItBelongsToOneFamily:
    def test_it_refuses_a_correction_from_another_family(self):
        ours = FamilyLexicon.empty(OURS)

        refused = ours.learn(correction(family_id=THEIRS, note="sanskaar"))

        assert refused.is_err()
        assert refused.unwrap_err().code is ErrorCode.PERMISSION_DENIED

    def test_the_refusal_says_which_two_families(self):
        # So that if this ever fires in production the log names the boundary that was
        # crossed rather than saying "denied".
        details = FamilyLexicon.empty(OURS).learn(correction(family_id=THEIRS)).unwrap_err().details
        assert details == {"lexicon": "fam-ours", "correction": "fam-theirs"}

    def test_there_is_no_way_to_combine_two_lexicons(self):
        # The point of the module, checked at the source rather than trusted. A merge
        # written next year would be the moment this product started training on families.
        tree = ast.parse(LEXICON_SOURCE)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        forbidden = {
            name
            for name in names
            if any(word in name.lower() for word in ("merge", "union", "combine", "from_many"))
        }
        assert forbidden == set(), f"a lexicon must not be combinable: {sorted(forbidden)}"

    def test_the_only_family_it_can_ever_answer_about_is_its_own(self):
        ours = taught(FamilyLexicon.empty(OURS), *[correction(note="sanskaar")] * 2)

        # Nothing on the type takes a family. There is no parameter through which another
        # family's question could arrive.
        assert ours.family_id == OURS
        assert ours.weights_for(LexiconField.INTENT, ["sanskaar"]) == {"TEACH": 1.0}


class TestOnlyAPersonTeachesIt:
    def test_a_correction_is_built_from_an_override_and_nothing_else(self):
        # `Correction` has no constructor that takes an `Inference`. An engine that learns
        # from its own guesses describes itself after a year, not the family.
        assert not hasattr(Correction, "from_inference")
        assert "Inference" not in LEXICON_SOURCE

    def test_it_will_not_learn_from_a_correction_to_nothing(self):
        with pytest.raises(ValueError, match="to something"):
            Correction(OURS, LexiconField.INTENT, "   ", ("sanskaar",), T0)

    def test_a_correction_happened_at_a_moment_with_a_timezone(self):
        with pytest.raises(ValueError, match="timezone"):
            Correction(OURS, LexiconField.INTENT, "TEACH", ("x",), datetime(2026, 3, 4))


class TestOnceIsNotAHabit:
    def test_one_correction_teaches_nothing_yet(self):
        once = taught(FamilyLexicon.empty(OURS), correction(note="sanskaar"))

        assert len(once) == 1, "it was counted"
        assert once.weights_for(LexiconField.INTENT, ["sanskaar"]) == {}, "and it stays quiet"

    def test_the_same_correction_twice_is_a_habit(self):
        twice = taught(FamilyLexicon.empty(OURS), *[correction(note="sanskaar")] * 2)

        assert twice.weights_for(LexiconField.INTENT, ["sanskaar"]) == {"TEACH": 1.0}

    def test_the_threshold_is_more_than_one(self):
        # Named rather than assumed, because a product that reorganises itself around a
        # single tap is a product that feels haunted.
        assert MIN_EVIDENCE_TO_SPEAK > 1

    def test_a_family_cannot_shout_the_engine_down_by_repetition(self):
        loud = taught(FamilyLexicon.empty(OURS), *[correction(note="sanskaar")] * 50)

        assert loud.weights_for(LexiconField.INTENT, ["sanskaar"]) == {"TEACH": MAX_WEIGHT}


class TestAWordUsedBothWaysStaysSilent:
    def test_a_term_corrected_two_ways_teaches_nothing(self):
        # "story" is a book in one half of this house and a thing Nani does at bedtime in
        # the other. Both are true, and the Spark in front of us does not say which.
        both = taught(
            FamilyLexicon.empty(OURS),
            *[correction(to="READ", note="story")] * 2,
            *[correction(to="TELL", note="story")] * 2,
        )

        assert both.weights_for(LexiconField.INTENT, ["story"]) == {}

    def test_it_does_not_take_the_side_with_more_taps(self):
        lopsided = taught(
            FamilyLexicon.empty(OURS),
            *[correction(to="READ", note="story")] * 9,
            *[correction(to="TELL", note="story")] * 2,
        )

        assert lopsided.weights_for(LexiconField.INTENT, ["story"]) == {}

    def test_an_ambiguous_word_does_not_silence_the_unambiguous_ones(self):
        mixed = taught(
            FamilyLexicon.empty(OURS),
            *[correction(to="READ", note="story bedtime")] * 2,
            *[correction(to="TELL", note="story")] * 2,
        )

        assert mixed.weights_for(LexiconField.INTENT, ["story", "bedtime"]) == {"READ": 1.0}

    def test_the_same_word_may_mean_different_things_in_different_fields(self):
        # An intent and a category are different questions, so "story" answering both is
        # not a contradiction.
        lexicon = taught(
            FamilyLexicon.empty(OURS),
            *[correction(field=LexiconField.INTENT, to="TELL", note="story")] * 2,
            *[correction(field=LexiconField.CATEGORY, to="bedtime", note="story")] * 2,
        )

        assert lexicon.weights_for(LexiconField.INTENT, ["story"]) == {"TELL": 1.0}
        assert lexicon.weights_for(LexiconField.CATEGORY, ["story"]) == {"bedtime": 1.0}


class TestWhatCountsAsAWord:
    def test_it_learns_the_words_a_parent_actually_wrote(self):
        assert terms_in("Balance bike for toddlers") == ("balance", "bike", "toddlers")

    def test_it_ignores_the_words_every_family_uses(self):
        assert terms_in("this is the one that you would like") == ()
        assert "the" in STOPWORDS

    def test_it_ignores_fragments_too_short_to_mean_anything(self):
        assert terms_in("a to go by") == ()

    def test_it_reads_a_word_once_however_often_it_appears(self):
        assert terms_in("bike bike bike", "bike") == ("bike",)

    def test_it_keeps_the_order_the_engine_sees(self):
        assert terms_in("title words", None, "note words") == ("title", "words", "note")

    def test_a_correction_on_a_spark_with_no_words_is_not_an_error(self):
        # A shared photograph with no caption. Nothing was said, so nothing is learned, and
        # that is a success - a family should not see a failure for correcting a picture.
        wordless = FamilyLexicon.empty(OURS).learn(correction(note="   "))

        assert wordless.is_ok()
        assert len(wordless.unwrap()) == 0


class TestItHoldsCountsAndCannotReconstructAnything:
    def test_the_module_never_names_a_spark_a_child_or_a_member(self):
        for forbidden in ("SparkId", "ChildId", "MemberId", "MediaId"):
            assert forbidden not in LEXICON_SOURCE, (
                f"a lexicon has no business knowing a {forbidden}"
            )

    def test_the_export_carries_terms_and_tallies_and_nothing_else(self):
        lexicon = taught(FamilyLexicon.empty(OURS), *[correction(note="sanskaar patience")] * 2)

        exported = lexicon.to_dict()

        assert exported["family_id"] == "fam-ours"
        assert {key for term in exported["terms"] for key in term} == {
            "field",
            "term",
            "means",
            "speaks",
            "times",
            "last_at",
        }

    def test_two_exports_of_the_same_lexicon_are_the_same_bytes(self):
        # So a family can diff last year's against this year's and see what changed.
        lexicon = taught(FamilyLexicon.empty(OURS), *[correction(note="zebra apple mango")] * 2)

        assert lexicon.to_dict() == FamilyLexicon(OURS, dict(lexicon.entries)).to_dict()
        terms = [entry["term"] for entry in lexicon.to_dict()["terms"]]
        assert terms == sorted(terms)


class TestForgetting:
    def test_one_word_can_be_unlearned_everywhere_it_appears(self):
        lexicon = taught(
            FamilyLexicon.empty(OURS),
            *[correction(field=LexiconField.INTENT, to="TELL", note="story")] * 2,
            *[correction(field=LexiconField.CATEGORY, to="bedtime", note="story")] * 2,
        )

        after = lexicon.forget("Story")

        assert len(after) == 0, "both fields, one call, and the case does not matter"

    def test_everything_can_be_deleted_and_the_family_survives_it(self):
        lexicon = taught(FamilyLexicon.empty(OURS), *[correction(note="sanskaar")] * 2)

        emptied = lexicon.forget_everything()

        assert len(emptied) == 0
        assert emptied.family_id == OURS

    def test_forgetting_a_word_it_never_knew_is_quiet(self):
        assert len(FamilyLexicon.empty(OURS).forget("aeroplane")) == 0


class TestItStaysAVocabularyAndNotAnArchive:
    def test_it_stops_growing(self):
        many = FamilyLexicon.empty(OURS)
        for index in range(MAX_TERMS + 50):
            many = many.learn(correction(note=made_up_word(index))).unwrap()

        assert len(many) == MAX_TERMS

    def test_it_evicts_the_weakest_and_keeps_the_habits(self):
        lexicon = taught(FamilyLexicon.empty(OURS), *[correction(note="sanskaar")] * 5)
        for index in range(MAX_TERMS + 50):
            lexicon = lexicon.learn(correction(note=made_up_word(index))).unwrap()

        assert lexicon.weights_for(LexiconField.INTENT, ["sanskaar"]) == {"TEACH": MAX_WEIGHT}

    def test_eviction_does_not_depend_on_dictionary_ordering(self):
        def fill(order: range) -> FamilyLexicon:
            lexicon = FamilyLexicon.empty(OURS)
            for index in order:
                lexicon = lexicon.learn(
                    correction(note=made_up_word(index), at=T0 + timedelta(seconds=index))
                ).unwrap()
            return lexicon

        assert fill(range(MAX_TERMS + 50)).to_dict() == fill(range(MAX_TERMS + 50)).to_dict()


class TestEvidence:
    def test_a_single_sighting_does_not_speak(self):
        assert Evidence(1, T0).speaks is False

    def test_the_weight_grows_and_then_stops(self):
        assert Evidence(2, T0).weight == 1.0
        assert Evidence(100, T0).weight == MAX_WEIGHT
