"""TASK-207 - the heuristic Intent Engine (PRD 13, ADR-0004).

PRD 13 calls intent understanding the core AI capability. PRD 8.1 says "Human Before AI"
and PRD 49 rules out advanced agents in V0. So V0 ships rules: offline, deterministic,
and honest about how sure it is. The port stays the same when an LLM replaces it.
"""

from __future__ import annotations

import pytest

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.ports import IntentEngine
from anuvritti.domain.values import Confidence, IntentType, SourceKind, SourceRef

ENGINE = HeuristicIntentEngine()


def _url(url: str, **kwargs) -> SourceRef:
    return SourceRef.from_url(url, **kwargs)


class TestPortConformance:
    def test_it_satisfies_the_intent_engine_port(self):
        assert isinstance(ENGINE, IntentEngine)

    def test_it_returns_a_plain_domain_inference(self):
        inference = ENGINE.infer(SourceRef.from_text("balloon rocket experiment"))
        assert inference.intent in IntentType.v0_set()


class TestIntentInference:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("balance bike for toddlers, buy now", IntentType.BUY),
            ("wooden train set price drop", IntentType.BUY),
            ("baking soda volcano experiment to try together", IntentType.DO),
            ("easy paper craft you can make at home", IntentType.DO),
            ("the best animated film for a rainy afternoon", IntentType.WATCH),
            ("bedtime story book about a lost elephant", IntentType.READ),
            ("how to teach a child about honesty", IntentType.TEACH),
            ("a lesson on saying sorry properly", IntentType.TEACH),
            ("something I want to remember", IntentType.REMEMBER),
        ],
    )
    def test_it_reads_the_intent_from_the_words(self, text, expected):
        assert ENGINE.infer(SourceRef.from_text(text)).intent is expected

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.youtube.com/watch?v=abc", IntentType.WATCH),
            ("https://www.amazon.in/dp/B0123", IntentType.BUY),
            ("https://www.goodreads.com/book/show/1", IntentType.READ),
        ],
    )
    def test_the_host_is_a_signal_when_the_words_are_not(self, url, expected):
        assert ENGINE.infer(_url(url)).intent is expected

    def test_the_note_the_parent_typed_outweighs_the_host(self):
        """PRD 8.1 - Human Before AI. What the parent said is the strongest evidence."""
        inference = ENGINE.infer(
            _url("https://www.amazon.in/dp/B0123", title="Balance bike"),
            note="I want to teach him to ride this summer",
        )
        assert inference.intent is IntentType.TEACH

    def test_unrecognised_content_falls_back_to_remember(self):
        """The honest answer to "I don't know" is "you wanted to remember this"."""
        assert ENGINE.infer(SourceRef.from_text("qwertyuiop zxcvb")).intent is IntentType.REMEMBER

    def test_it_only_ever_produces_a_v0_intent(self):
        """PRD 48 F4 - a recipe is a DO in V0; COOK is a V1 decision, not a surprise."""
        inference = ENGINE.infer(SourceRef.from_text("one pot dal recipe for kids"))
        assert inference.intent.is_available_in_v0


class TestConfidence:
    def test_it_never_claims_certainty(self):
        """PRD 8.7 - AI interpretation is not recorded truth. CERTAIN is for humans only."""
        strong = ENGINE.infer(
            _url("https://www.amazon.in/dp/B1", title="Wooden balance bike to buy for toddlers")
        )
        assert strong.intent_confidence < Confidence.CERTAIN

    def test_a_clear_signal_is_more_confident_than_a_vague_one(self):
        clear = ENGINE.infer(SourceRef.from_text("science experiment to do with your kids"))
        vague = ENGINE.infer(SourceRef.from_text("nice"))
        assert clear.intent_confidence > vague.intent_confidence

    def test_the_fallback_is_marked_as_low_confidence(self):
        inference = ENGINE.infer(SourceRef.from_text("zzz"))
        assert inference.intent_confidence.is_low

    def test_every_confidence_is_a_probability(self):
        inference = ENGINE.infer(SourceRef.from_text("dinosaur museum trip for a 5 year old"))
        assert 0.0 <= inference.intent_confidence.value <= 1.0
        assert 0.0 <= inference.category_confidence.value <= 1.0
        if inference.age_confidence:
            assert 0.0 <= inference.age_confidence.value <= 1.0


class TestAgeInference:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("great for ages 3-5", (3, 5)),
            ("suitable for 4 to 7 year olds", (4, 7)),
            ("perfect for a 6 year old", (6, 6)),
            ("toddler friendly activity", (1, 3)),
            ("preschool science", (3, 5)),
        ],
    )
    def test_it_reads_an_age_range_out_of_the_text(self, text, expected):
        inference = ENGINE.infer(SourceRef.from_text(text))
        assert inference.age_range is not None
        assert (inference.age_range.min_years, inference.age_range.max_years) == expected

    def test_it_leaves_the_age_unset_rather_than_guessing(self):
        """An invented age range would quietly distort every future suggestion."""
        assert ENGINE.infer(SourceRef.from_text("a thought about patience")).age_range is None

    def test_an_impossible_age_range_is_discarded_not_clamped_silently(self):
        assert ENGINE.infer(SourceRef.from_text("for ages 40-90")).age_range is None

    def test_a_reversed_range_is_normalised(self):
        inference = ENGINE.infer(SourceRef.from_text("ages 7-3"))
        assert inference.age_range is not None
        assert inference.age_range.min_years <= inference.age_range.max_years


class TestCategoryAndTags:
    @pytest.mark.parametrize(
        "text,category",
        [
            ("wooden balance bike", "toy"),
            ("baking soda volcano experiment", "science-activity"),
            ("one pot dal recipe", "food"),
            ("bedtime story book", "book"),
            ("animated film about a robot", "film"),
            ("dinosaur museum in the city", "place"),
            ("how to teach patience", "life-skill"),
        ],
    )
    def test_it_categorises_recognisable_things(self, text, category):
        assert ENGINE.infer(SourceRef.from_text(text)).category == category

    def test_unrecognised_content_is_uncategorised_not_mislabelled(self):
        assert ENGINE.infer(SourceRef.from_text("qwerty")).category == "uncategorised"

    def test_tags_are_deduplicated_and_lowercase(self):
        tags = ENGINE.infer(SourceRef.from_text("outdoor science science experiment")).tags
        assert len(tags) == len(set(tags))
        assert all(tag == tag.lower() for tag in tags)

    def test_tags_are_bounded(self):
        """A hundred tags is the same as no tags."""
        text = " ".join(["science", "outdoor", "toy", "book", "film", "food", "craft"] * 5)
        assert len(ENGINE.infer(SourceRef.from_text(text)).tags) <= 6


class TestTitle:
    def test_it_prefers_the_title_the_source_already_had(self):
        inference = ENGINE.infer(_url("https://x.com/a", title="Balloon rocket"))
        assert inference.title == "Balloon rocket"

    def test_it_falls_back_to_the_captured_text(self):
        assert ENGINE.infer(SourceRef.from_text("Teach him to whistle")).title == (
            "Teach him to whistle"
        )

    def test_it_falls_back_to_the_host_for_a_bare_link(self):
        assert ENGINE.infer(_url("https://instagram.com/reel/a")).title == "instagram.com"

    def test_a_media_capture_gets_a_readable_placeholder(self):
        inference = ENGINE.infer(SourceRef.from_media(SourceKind.VOICE, media_id="med-1"))
        assert inference.title


class TestDeterminismAndPurity:
    def test_the_same_input_always_produces_the_same_inference(self):
        source = SourceRef.from_text("science experiment for a 5 year old")
        first, second = ENGINE.infer(source), ENGINE.infer(source)
        assert first == second

    def test_two_engine_instances_agree(self):
        source = SourceRef.from_text("wooden train set")
        assert HeuristicIntentEngine().infer(source) == HeuristicIntentEngine().infer(source)

    def test_it_makes_no_network_call(self):
        """PRD 44 - "no public-model training by default", honoured by sending nothing."""
        import socket

        original = socket.socket

        def forbidden(*args, **kwargs):
            raise AssertionError("the intent engine must never open a socket")

        socket.socket = forbidden  # type: ignore[misc, assignment]
        try:
            ENGINE.infer(_url("https://www.youtube.com/watch?v=abc", title="Volcano"))
        finally:
            socket.socket = original  # type: ignore[misc]

    def test_it_handles_empty_and_hostile_input_without_crashing(self):
        for source in (
            SourceRef.from_text("   x   "),
            SourceRef.from_text("<script>alert(1)</script>"),
            SourceRef.from_text("ages -5 to -1"),
            SourceRef.from_text("🎈" * 200),
        ):
            assert ENGINE.infer(source).intent in IntentType.v0_set()
