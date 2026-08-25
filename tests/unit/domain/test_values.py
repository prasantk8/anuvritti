"""TASK-201 - domain value objects.

These encode PRD promises that must not be re-litigated in code review: six V0 intents,
provenance on every AI-derived field, and a Spark that survives link rot.
"""

from __future__ import annotations

import pytest

from anuvritti.domain.values import (
    AgeRange,
    Attributed,
    AttributionSource,
    Confidence,
    IntentType,
    MemberRole,
    SourceKind,
    SourceRef,
    SparkStatus,
    Visibility,
)


class TestIntentType:
    def test_v0_ships_exactly_the_six_intents_the_prd_names(self):
        """PRD 48 F4 - DO, BUY, WATCH, READ, TEACH, REMEMBER. 'Enough for V0.'"""
        assert IntentType.v0_set() == frozenset(
            {
                IntentType.DO,
                IntentType.BUY,
                IntentType.WATCH,
                IntentType.READ,
                IntentType.TEACH,
                IntentType.REMEMBER,
            }
        )

    def test_later_intents_are_modelled_but_gated_off(self):
        """PRD 10 lists COOK/VISIT/TELL/LISTEN; V1 enables them without a migration."""
        assert IntentType.COOK not in IntentType.v0_set()
        assert IntentType.COOK.is_available_in_v0 is False
        assert IntentType.DO.is_available_in_v0 is True

    def test_parsing_an_unknown_intent_fails_loudly(self):
        with pytest.raises(ValueError, match="INVENT"):
            IntentType("INVENT")

    @pytest.mark.parametrize(
        "intent,expected",
        [
            (IntentType.DO, True),
            (IntentType.TEACH, True),
            (IntentType.BUY, False),
            (IntentType.REMEMBER, False),
        ],
    )
    def test_actionability_distinguishes_do_now_from_hold(self, intent, expected):
        """PRD 13 - urgency differs by intent; the Return Engine leans on this."""
        assert intent.is_immediately_actionable is expected


class TestSparkStatus:
    def test_terminal_states_are_marked(self):
        assert SparkStatus.ARCHIVED.is_terminal is True
        assert SparkStatus.REMEMBERED.is_terminal is True
        assert SparkStatus.WAITING.is_terminal is False

    def test_returnable_states_are_the_ones_the_engine_may_surface(self):
        assert SparkStatus.WAITING.is_returnable is True
        assert SparkStatus.RELEVANT.is_returnable is True
        assert SparkStatus.EXPERIENCED.is_returnable is False
        assert SparkStatus.ARCHIVED.is_returnable is False

    def test_lived_states_represent_something_that_actually_happened(self):
        assert SparkStatus.EXPERIENCED.is_lived is True
        assert SparkStatus.PLANNED.is_lived is False


class TestConfidence:
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_accepts_the_unit_interval(self, value):
        assert Confidence(value).value == value

    @pytest.mark.parametrize("value", [-0.01, 1.01, 42.0])
    def test_rejects_values_outside_the_unit_interval(self, value):
        with pytest.raises(ValueError, match="between 0 and 1"):
            Confidence(value)

    def test_named_levels_are_ordered(self):
        assert Confidence.LOW < Confidence.MEDIUM < Confidence.HIGH

    def test_is_low_flags_fields_a_human_should_check(self):
        assert Confidence(0.2).is_low is True
        assert Confidence(0.9).is_low is False

    def test_certain_is_reserved_for_human_statements(self):
        assert Confidence.CERTAIN.value == 1.0


class TestAgeRange:
    def test_contains_is_inclusive_at_both_ends(self):
        age_range = AgeRange(2, 5)
        assert age_range.contains(2) and age_range.contains(5)
        assert not age_range.contains(1) and not age_range.contains(6)

    def test_a_single_year_range_is_valid(self):
        assert AgeRange(3, 3).contains(3)

    def test_min_may_not_exceed_max(self):
        with pytest.raises(ValueError, match="min_years"):
            AgeRange(6, 2)

    def test_negative_ages_are_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            AgeRange(-1, 3)

    def test_absurd_ages_are_rejected(self):
        with pytest.raises(ValueError, match="18"):
            AgeRange(2, 40)

    def test_distance_from_is_zero_inside_the_range(self):
        assert AgeRange(2, 5).years_until(3) == 0

    def test_distance_from_counts_years_until_the_child_is_ready(self):
        """Drives 'he may be ready now' (PRD 48 F6)."""
        assert AgeRange(6, 8).years_until(4) == 2

    def test_distance_is_zero_once_the_child_has_outgrown_it(self):
        assert AgeRange(2, 3).years_until(9) == 0

    def test_ranges_are_comparable_by_value(self):
        assert AgeRange(2, 5) == AgeRange(2, 5)


class TestAttributed:
    def test_ai_inference_records_its_own_provenance(self):
        """PRD 13/42 - value, source, confidence, human_override."""
        field = Attributed.inferred(IntentType.DO, Confidence(0.7))
        assert field.value is IntentType.DO
        assert field.source is AttributionSource.AI
        assert field.confidence == Confidence(0.7)
        assert field.human_override is False

    def test_a_human_statement_is_certain_and_marked_as_an_override(self):
        field = Attributed.stated(IntentType.BUY)
        assert field.source is AttributionSource.HUMAN
        assert field.confidence == Confidence.CERTAIN
        assert field.human_override is True

    def test_a_default_carries_no_confidence(self):
        field = Attributed.defaulted(IntentType.REMEMBER)
        assert field.source is AttributionSource.DEFAULT
        assert field.confidence == Confidence(0.0)

    def test_overriding_replaces_the_value_and_locks_the_field(self):
        overridden = Attributed.inferred(IntentType.DO, Confidence(0.9)).override(IntentType.TEACH)
        assert overridden.value is IntentType.TEACH
        assert overridden.human_override is True
        assert overridden.source is AttributionSource.HUMAN

    def test_the_human_is_never_overwritten_by_a_later_inference(self):
        """PRD 13 - human override always wins."""
        human = Attributed.stated(IntentType.BUY)
        assert human.may_reinfer is False
        assert human.reinferred(IntentType.WATCH, Confidence(0.99)) == human

    def test_an_ai_field_may_be_reinferred(self):
        ai = Attributed.inferred(IntentType.DO, Confidence(0.4))
        improved = ai.reinferred(IntentType.WATCH, Confidence(0.8))
        assert improved.value is IntentType.WATCH
        assert improved.may_reinfer is True

    def test_serialises_with_its_provenance_intact(self):
        payload = Attributed.inferred(IntentType.DO, Confidence(0.75)).to_dict()
        assert payload == {
            "value": "DO",
            "source": "AI",
            "confidence": 0.75,
            "human_override": False,
        }

    def test_is_immutable(self):
        field = Attributed.inferred(IntentType.DO, Confidence(0.5))
        with pytest.raises(AttributeError):
            field.value = IntentType.BUY  # type: ignore[misc]

    def test_holds_any_value_type(self):
        field = Attributed.inferred(AgeRange(2, 5), Confidence(0.6))
        assert field.value == AgeRange(2, 5)


class TestSourceRef:
    def test_a_url_source_keeps_creator_and_title_for_when_the_link_dies(self):
        """PRD 43 - a Spark must never become empty because the internet changed."""
        source = SourceRef.from_url(
            "https://instagram.com/reel/abc", creator="@sciencedad", title="Balloon rocket"
        )
        assert source.kind is SourceKind.URL
        assert source.retains_meaning_without_network is True

    def test_a_bare_url_with_no_preserved_context_does_not_retain_meaning(self):
        source = SourceRef.from_url("https://instagram.com/reel/abc")
        assert source.retains_meaning_without_network is False

    def test_url_must_be_http_or_https(self):
        with pytest.raises(ValueError, match="http"):
            SourceRef.from_url("javascript:alert(1)")

    def test_url_must_be_well_formed(self):
        with pytest.raises(ValueError, match="host"):
            SourceRef.from_url("https://")

    def test_a_text_source_requires_text(self):
        with pytest.raises(ValueError, match="text"):
            SourceRef.from_text("   ")

    def test_a_text_source_always_retains_meaning(self):
        assert SourceRef.from_text("teach him to whistle").retains_meaning_without_network is True

    def test_a_media_source_references_stored_bytes(self):
        source = SourceRef.from_media(SourceKind.VOICE, media_id="med-1")
        assert source.media_id == "med-1"
        assert source.retains_meaning_without_network is True

    def test_a_media_source_requires_a_media_id(self):
        with pytest.raises(ValueError, match="media_id"):
            SourceRef.from_media(SourceKind.PHOTO, media_id="")

    def test_a_media_source_rejects_a_non_media_kind(self):
        with pytest.raises(ValueError, match="kind"):
            SourceRef.from_media(SourceKind.URL, media_id="med-1")

    def test_display_title_falls_back_through_title_then_text_then_host(self):
        assert SourceRef.from_url("https://x.com/a", title="Rocket").display_title() == "Rocket"
        assert SourceRef.from_text("Balloon rocket").display_title() == "Balloon rocket"
        assert SourceRef.from_url("https://instagram.com/reel/a").display_title() == "instagram.com"

    def test_display_title_is_truncated_for_long_text(self):
        assert len(SourceRef.from_text("word " * 60).display_title()) <= 80


class TestVisibilityAndRoles:
    def test_visibility_levels_are_ordered_from_most_to_least_private(self):
        assert Visibility.PRIVATE.is_more_private_than(Visibility.FAMILY)
        assert Visibility.FAMILY.is_more_private_than(Visibility.CHILD_VISIBLE)

    def test_child_visible_content_is_visible_to_the_family(self):
        assert Visibility.CHILD_VISIBLE.is_visible_to(MemberRole.CHILD) is True
        assert Visibility.CHILD_VISIBLE.is_visible_to(MemberRole.PARENT) is True

    def test_private_content_is_not_visible_to_the_child_or_grandparents(self):
        assert Visibility.PRIVATE.is_visible_to(MemberRole.CHILD) is False
        assert Visibility.PRIVATE.is_visible_to(MemberRole.GRANDPARENT) is False

    def test_family_visibility_excludes_the_child_until_shared_explicitly(self):
        """PRD 45 - a parent's private note about a child is not the child's feed."""
        assert Visibility.FAMILY.is_visible_to(MemberRole.CO_PARENT) is True
        assert Visibility.FAMILY.is_visible_to(MemberRole.CHILD) is False

    def test_only_parents_may_capture_on_a_childs_behalf(self):
        assert MemberRole.PARENT.can_capture_for_child is True
        assert MemberRole.CO_PARENT.can_capture_for_child is True
        assert MemberRole.GRANDPARENT.can_capture_for_child is False

    def test_the_default_visibility_is_the_most_private_one(self):
        """Privacy by default, not by configuration (PRD 44)."""
        assert Visibility.default() is Visibility.PRIVATE
