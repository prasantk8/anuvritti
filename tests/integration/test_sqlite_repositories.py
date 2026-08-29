"""TASK-213 - SQLite persistence (ADR-0003).

The archive is meant to outlive this codebase, so these tests care about two things:
the data round-trips without losing meaning, and provenance survives storage intact.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from anuvritti.adapters.persistence.schema import SCHEMA_VERSION, connect, migrate
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.domain.spark import Inference, Spark
from anuvritti.domain.values import (
    AgeRange,
    AttributionSource,
    Confidence,
    IntentType,
    SourceKind,
    SourceRef,
    SparkStatus,
    Visibility,
)
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import (
    FamilyId,
    LittleThingId,
    MomentId,
    RightNowId,
    SparkId,
)
from tests.integration.conftest import CHILD, FAMILY, PAPA

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)


def _spark(spark_id: str = "spk-1", **kwargs) -> Spark:
    spark = Spark.capture(
        spark_id=SparkId(spark_id),
        family_id=FAMILY,
        owner_id=PAPA,
        subject_child_id=CHILD,
        source=SourceRef.from_url(
            "https://instagram.com/reel/abc", creator="@sciencedad", title="Balloon rocket"
        ),
        note=kwargs.get("note"),
        visibility=kwargs.get("visibility", Visibility.PRIVATE),
        at=T0,
    )
    return spark.apply_inference(
        Inference(
            title="Balloon rocket",
            intent=IntentType.DO,
            intent_confidence=Confidence(0.8),
            category="science-activity",
            category_confidence=Confidence(0.7),
            age_range=AgeRange(4, 7),
            age_confidence=Confidence(0.6),
            tags=("science", "outdoor"),
        )
    ).with_events_cleared()


class TestMigrations:
    def test_migrating_a_fresh_database_reports_the_schema_version(self, tmp_path):
        connection = connect(str(tmp_path / "fresh.db"))
        assert migrate(connection) == SCHEMA_VERSION

    def test_migrations_are_idempotent(self, tmp_path):
        connection = connect(str(tmp_path / "twice.db"))
        migrate(connection)
        migrate(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    def test_write_ahead_logging_is_enabled(self, db):
        """A crash mid-write must not cost a family their archive."""
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

    def test_foreign_keys_are_enforced_so_deletion_cascades(self, db):
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


class TestFamilyRepository:
    def test_a_family_round_trips(self, repos, seeded_family):
        loaded = repos.families.get(FAMILY).unwrap()
        assert loaded.name == seeded_family.name
        assert loaded.members[0].display_name == "Papa"

    def test_children_round_trip_with_their_date_of_birth(self, repos, seeded_family):
        child = repos.families.get(FAMILY).unwrap().child(CHILD).unwrap()
        assert child.date_of_birth == date(2021, 6, 1)
        assert child.age_years(date(2026, 8, 25)) == 5

    def test_an_unknown_family_is_an_error_not_an_exception(self, repos):
        assert repos.families.get(FamilyId("nope")).unwrap_err().code is ErrorCode.FAMILY_NOT_FOUND

    def test_saving_twice_updates_rather_than_duplicates(self, repos, seeded_family):
        repos.families.save(seeded_family)
        assert len(repos.families.get(FAMILY).unwrap().members) == 1


class TestSparkRepository:
    def test_a_spark_round_trips(self, repos, seeded_family):
        repos.sparks.save(_spark())
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.title == "Balloon rocket"
        assert loaded.status is SparkStatus.WAITING

    def test_provenance_survives_storage(self, repos, seeded_family):
        """ADR-0005 - an AI guess must never come back looking like a fact."""
        repos.sparks.save(_spark())
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.intent.source is AttributionSource.AI
        assert loaded.intent.confidence == Confidence(0.8)
        assert loaded.intent.human_override is False

    def test_a_human_override_survives_storage(self, repos, seeded_family):
        repos.sparks.save(_spark().override_intent(IntentType.TEACH).unwrap())
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.intent.human_override is True
        assert loaded.intent.source is AttributionSource.HUMAN

    def test_the_source_context_survives_so_the_spark_outlives_the_link(self, repos, seeded_family):
        """PRD 43 - a Spark must never become empty because the internet changed."""
        repos.sparks.save(_spark())
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.source.creator == "@sciencedad"
        assert loaded.retains_meaning_without_network is True

    def test_the_age_range_and_tags_survive(self, repos, seeded_family):
        repos.sparks.save(_spark())
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.age_range.value == AgeRange(4, 7)
        assert loaded.tags == ("science", "outdoor")

    def test_a_spark_with_no_age_range_round_trips_as_none(self, repos, seeded_family):
        bare = Spark.capture(
            spark_id=SparkId("spk-bare"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_text("a thought about patience"),
            at=T0,
        ).with_events_cleared()
        repos.sparks.save(bare)
        assert repos.sparks.get(SparkId("spk-bare")).unwrap().age_range is None

    def test_the_why_survives_with_its_timestamp(self, repos, seeded_family):
        spark = _spark().record_why(text="I never had one growing up", at=T0).unwrap()
        repos.sparks.save(spark)
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.why.text == "I never had one growing up"
        assert loaded.why.recorded_at == T0

    def test_a_voice_why_round_trips(self, repos, seeded_family):
        spark = _spark().record_why(voice_media_id="med-9", at=T0).unwrap()
        repos.sparks.save(spark)
        assert repos.sparks.get(SparkId("spk-1")).unwrap().why.voice_media_id == "med-9"

    def test_saving_the_same_spark_twice_updates_it(self, repos, seeded_family):
        repos.sparks.save(_spark())
        repos.sparks.save(_spark().override_category("toy").unwrap())
        assert repos.sparks.get(SparkId("spk-1")).unwrap().category.value == "toy"
        assert len(repos.sparks.list_for_family(FAMILY).unwrap()) == 1

    def test_lifecycle_state_survives(self, repos, seeded_family):
        spark = _spark().mark_suggested(T0 + timedelta(days=200), score=0.7).unwrap()
        repos.sparks.save(spark)
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.status is SparkStatus.SUGGESTED
        assert loaded.suggested_count == 1
        assert loaded.last_suggested_at == T0 + timedelta(days=200)

    def test_a_snooze_survives(self, repos, seeded_family):
        spark = _spark().mark_suggested(T0, score=0.5).unwrap()
        spark = spark.snooze(until=T0 + timedelta(days=30)).unwrap()
        repos.sparks.save(spark)
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.is_snoozed_at(T0 + timedelta(days=10)) is True

    def test_an_unknown_spark_is_an_error(self, repos):
        assert repos.sparks.get(SparkId("nope")).unwrap_err().code is ErrorCode.SPARK_NOT_FOUND

    @pytest.mark.parametrize("kind", list(SourceKind))
    def test_every_source_kind_round_trips(self, repos, seeded_family, kind):
        source = (
            SourceRef.from_url("https://x.com/a", title="t")
            if kind is SourceKind.URL
            else SourceRef.from_text("t")
            if kind is SourceKind.TEXT
            else SourceRef.from_imported(title="t", text="imported")
            if kind is SourceKind.IMPORTED
            else SourceRef.from_media(kind, media_id="med-1")
        )
        spark = Spark.capture(
            spark_id=SparkId(f"spk-{kind.value}"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=source,
            at=T0,
        ).with_events_cleared()
        repos.sparks.save(spark)
        assert repos.sparks.get(SparkId(f"spk-{kind.value}")).unwrap().source.kind is kind


class TestSparkSearch:
    @pytest.fixture(autouse=True)
    def _archive(self, repos, seeded_family):
        for index, (title, note, intent, ages) in enumerate(
            [
                ("Wooden balance bike", "for his birthday", IntentType.BUY, AgeRange(2, 5)),
                ("Volcano experiment", "do this outside", IntentType.DO, AgeRange(5, 8)),
                ("Space rockets explained", None, IntentType.WATCH, AgeRange(6, 10)),
                ("Teaching honesty", "I want to teach him", IntentType.TEACH, None),
            ]
        ):
            spark = Spark.capture(
                spark_id=SparkId(f"spk-{index}"),
                family_id=FAMILY,
                owner_id=PAPA,
                subject_child_id=CHILD,
                source=SourceRef.from_url(f"https://x.com/{index}", title=title),
                note=note,
                at=T0 + timedelta(days=index),
            ).apply_inference(
                Inference(
                    title=title,
                    intent=intent,
                    intent_confidence=Confidence(0.7),
                    category="thing",
                    category_confidence=Confidence(0.5),
                    age_range=ages,
                    age_confidence=Confidence(0.6) if ages else None,
                    tags=("tag",),
                )
            )
            repos.sparks.save(spark.with_events_cleared())

    def test_text_search_matches_the_title(self, repos):
        found = repos.sparks.search(FAMILY, text="volcano").unwrap()
        assert [s.title for s in found] == ["Volcano experiment"]

    def test_text_search_matches_the_parents_note(self, repos):
        found = repos.sparks.search(FAMILY, text="outside").unwrap()
        assert len(found) == 1

    def test_text_search_is_case_insensitive(self, repos):
        assert len(repos.sparks.search(FAMILY, text="VOLCANO").unwrap()) == 1

    def test_intent_filter_works(self, repos):
        found = repos.sparks.search(FAMILY, intent=IntentType.BUY).unwrap()
        assert all(s.intent.value is IntentType.BUY for s in found)

    def test_age_filter_includes_sparks_with_no_age_range(self, repos):
        """Absence of a guess is not a statement that something is unsuitable."""
        found = repos.sparks.search(FAMILY, age_years=3).unwrap()
        titles = {s.title for s in found}
        assert "Wooden balance bike" in titles
        assert "Teaching honesty" in titles
        assert "Space rockets explained" not in titles

    def test_results_are_newest_first(self, repos):
        found = repos.sparks.search(FAMILY).unwrap()
        assert next(s.title for s in found) == "Teaching honesty"

    def test_the_limit_is_honoured(self, repos):
        assert len(repos.sparks.search(FAMILY, limit=2).unwrap()) == 2

    def test_a_sql_injection_attempt_is_treated_as_text(self, repos):
        """Parameterised throughout - a family archive is not a place to be clever."""
        found = repos.sparks.search(FAMILY, text="'; DROP TABLE spark; --").unwrap()
        assert found == []
        assert len(repos.sparks.list_for_family(FAMILY).unwrap()) == 4

    def test_returnable_listing_excludes_lived_and_archived_sparks(self, repos):
        spark = repos.sparks.get(SparkId("spk-0")).unwrap()
        repos.sparks.save(spark.archive().unwrap())
        returnable = repos.sparks.list_returnable(FAMILY).unwrap()
        assert all(s.status.is_returnable for s in returnable)
        assert len(returnable) == 3


class TestMomentRepository:
    def test_a_moment_round_trips(self, repos, seeded_family):
        repos.sparks.save(_spark())
        moment = Moment.create(
            moment_id=MomentId("mom-1"),
            family_id=FAMILY,
            spark_id=SparkId("spk-1"),
            created_by=PAPA,
            spark_captured_at=T0,
            at=T0 + timedelta(days=243),
            reflection="He laughed until he fell over.",
        ).unwrap()
        repos.moments.save(moment)
        loaded = repos.moments.get(MomentId("mom-1")).unwrap()
        assert loaded.reflection == "He laughed until he fell over."
        assert loaded.happened_on == (T0 + timedelta(days=243)).date()

    def test_a_moment_with_nothing_attached_round_trips(self, repos, seeded_family):
        moment = Moment.create(
            moment_id=MomentId("mom-2"),
            family_id=FAMILY,
            spark_id=SparkId("spk-2"),
            created_by=PAPA,
            spark_captured_at=T0,
            at=T0 + timedelta(days=1),
        ).unwrap()
        repos.moments.save(moment)
        assert repos.moments.get(MomentId("mom-2")).unwrap().has_evidence is False

    def test_it_can_be_found_by_its_spark(self, repos, seeded_family):
        moment = Moment.create(
            moment_id=MomentId("mom-3"),
            family_id=FAMILY,
            spark_id=SparkId("spk-9"),
            created_by=PAPA,
            spark_captured_at=T0,
            at=T0 + timedelta(days=1),
        ).unwrap()
        repos.moments.save(moment)
        assert repos.moments.find_by_spark(SparkId("spk-9")).unwrap().id == MomentId("mom-3")

    def test_a_spark_can_only_become_one_moment(self, repos, seeded_family):
        """Enforced by the database, not only by the use case."""
        for moment_id in ("mom-a", "mom-b"):
            moment = Moment.create(
                moment_id=MomentId(moment_id),
                family_id=FAMILY,
                spark_id=SparkId("spk-same"),
                created_by=PAPA,
                spark_captured_at=T0,
                at=T0 + timedelta(days=1),
            ).unwrap()
            result = repos.moments.save(moment)
        assert result.unwrap_err().code is ErrorCode.CONFLICT

    def test_an_unknown_moment_is_an_error(self, repos):
        assert repos.moments.get(MomentId("nope")).unwrap_err().code is ErrorCode.MOMENT_NOT_FOUND


class TestPresenceRepositories:
    def test_a_little_thing_round_trips(self, repos, seeded_family):
        thing = LittleThing.capture(
            little_thing_id=LittleThingId("lt-1"),
            family_id=FAMILY,
            author_id=PAPA,
            subject_child_id=CHILD,
            text="He called the moon a broken sun.",
            at=T0,
        ).unwrap()
        repos.little_things.save(thing)
        loaded = repos.little_things.list_for_family(FAMILY).unwrap()
        assert loaded[0].text == "He called the moon a broken sun."

    def test_a_voice_only_little_thing_round_trips(self, repos, seeded_family):
        thing = LittleThing.capture(
            little_thing_id=LittleThingId("lt-2"),
            family_id=FAMILY,
            author_id=PAPA,
            audio_media_id="med-1",
            at=T0,
        ).unwrap()
        repos.little_things.save(thing)
        assert repos.little_things.list_for_family(FAMILY).unwrap()[0].audio_media_id == "med-1"

    def test_a_right_now_snapshot_round_trips(self, repos, seeded_family):
        snapshot = RightNowSnapshot.capture(
            right_now_id=RightNowId("rn-1"),
            family_id=FAMILY,
            child_id=CHILD,
            prompt="What is he obsessed with this week?",
            answer="Volcanoes. Only volcanoes.",
            at=T0,
        ).unwrap()
        repos.right_now.save(snapshot)
        assert repos.right_now.list_for_family(FAMILY).unwrap()[0].answer.startswith("Volcanoes")

    def test_snapshots_come_back_newest_first(self, repos, seeded_family):
        for index, answer in enumerate(("Trains", "Volcanoes", "Space")):
            RightNowSnapshot.capture(
                right_now_id=RightNowId(f"rn-{index}"),
                family_id=FAMILY,
                child_id=CHILD,
                prompt="What is he obsessed with this week?",
                answer=answer,
                at=T0 + timedelta(days=index * 30),
            ).map(repos.right_now.save)
        assert repos.right_now.list_for_family(FAMILY).unwrap()[0].answer == "Space"


class TestEventTrail:
    def test_events_are_recorded_with_structural_payloads_only(self, repos, seeded_family):
        spark = _spark(note="something private")
        repos.events.publish(
            Spark.capture(
                spark_id=SparkId("spk-e"),
                family_id=FAMILY,
                owner_id=PAPA,
                source=spark.source,
                note="something private",
                at=T0,
            ).pending_events,
            family_id=FAMILY,
        )
        recorded = repos.events.raw_for_family(FAMILY)
        assert recorded[0]["name"] == "SparkCaptured"
        assert "private" not in str(recorded[0]["payload"])

    def test_the_trail_is_ordered(self, repos, seeded_family):
        spark = _spark()
        repos.events.publish(spark.pending_events, family_id=FAMILY)
        marked = spark.mark_suggested(T0 + timedelta(days=200), score=0.6).unwrap()
        repos.events.publish(marked.pending_events, family_id=FAMILY)
        names = [e["name"] for e in repos.events.raw_for_family(FAMILY)]
        assert names[-1] == "SparkSuggested"


class TestTransactions:
    def test_a_failed_transaction_leaves_nothing_behind(self, repos, seeded_family):
        with pytest.raises(RuntimeError), repos.uow:
            repos.sparks.save(_spark("spk-rollback"))
            raise RuntimeError("something went wrong mid-write")
        assert repos.sparks.get(SparkId("spk-rollback")).is_err()

    def test_a_committed_transaction_persists(self, repos, seeded_family):
        with repos.uow:
            repos.sparks.save(_spark("spk-commit"))
        assert repos.sparks.get(SparkId("spk-commit")).is_ok()

    def test_an_explicit_rollback_discards_the_write(self, repos, seeded_family):
        with repos.uow:
            repos.sparks.save(_spark("spk-manual"))
            repos.uow.rollback()
        assert repos.sparks.get(SparkId("spk-manual")).is_err()


class TestDurability:
    def test_the_archive_survives_reopening_the_file(self, tmp_path, repos, seeded_family):
        """The point of local-first: the family owns a file, not a session."""
        repos.sparks.save(_spark())
        path = repos.db.execute("PRAGMA database_list").fetchone()["file"]
        repos.db.close()

        reopened = connect(path)
        migrate(reopened)
        from anuvritti.adapters.persistence.sqlite import SqliteSparkRepository

        loaded = SqliteSparkRepository(reopened).get(SparkId("spk-1")).unwrap()
        assert loaded.title == "Balloon rocket"
        reopened.close()

    def test_unicode_survives_intact(self, repos, seeded_family):
        spark = _spark().record_why(text="वह चाँद को टूटा सूरज कहता है 🌙", at=T0).unwrap()
        repos.sparks.save(spark)
        assert repos.sparks.get(SparkId("spk-1")).unwrap().why.text.endswith("🌙")
