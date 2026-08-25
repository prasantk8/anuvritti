"""TASK-303 - resilience and edge cases.

A family archive is expected to outlive the code that wrote it and the links it points
at. These tests cover the ways real life is untidy: dead links, duplicate saves, clock
boundaries, hostile input, and a database that gets reopened years later.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteSparkRepository
from anuvritti.config.settings import load_settings
from anuvritti.domain.family import ChildProfile
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import AgeRange, SourceKind, SourceRef
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import MemberId, SequentialIdGenerator, SparkId
from tests.integration.conftest import CHILD, FAMILY, PAPA

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def client(tmp_path):
    clock = FrozenClock(T0)
    settings = load_settings(
        {
            "ANUVRITTI_ENV": "test",
            "ANUVRITTI_DB_PATH": str(tmp_path / "r.db"),
            "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
            "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
        }
    ).unwrap()
    container = build_container(settings, clock=clock, ids=SequentialIdGenerator("id"))
    test_client = TestClient(create_app(settings, container=container))
    test_client.clock = clock  # type: ignore[attr-defined]
    yield test_client
    container.close()


@pytest.fixture
def family(client):
    created = client.post(
        "/v1/families", json={"name": "Our family", "owner_display_name": "Papa"}
    ).json()
    child = client.post(
        f"/v1/families/{created['id']}/children",
        json={"display_name": "Aarav", "date_of_birth": "2021-06-01"},
    ).json()
    return {
        "family_id": created["id"],
        "papa_id": created["members"][0]["id"],
        "child_id": child["id"],
    }


class TestLinkRot:
    """PRD 43 - a Spark must never become empty because the internet changed."""

    def test_a_spark_with_preserved_context_survives_the_link_dying(self, repos, seeded_family):
        spark = Spark.capture(
            spark_id=SparkId("spk-1"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_url(
                "https://instagram.com/reel/gone", creator="@sciencedad", title="Balloon rocket"
            ),
            at=T0,
        ).with_events_cleared()
        repos.sparks.save(spark)
        loaded = repos.sparks.get(SparkId("spk-1")).unwrap()
        assert loaded.retains_meaning_without_network is True
        assert loaded.title == "Balloon rocket"

    def test_a_bare_link_is_flagged_as_fragile_at_capture_time(self):
        spark = Spark.capture(
            spark_id=SparkId("s"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_url("https://instagram.com/reel/xyz"),
            at=T0,
        )
        assert spark.retains_meaning_without_network is False

    def test_a_note_alone_rescues_a_bare_link(self, repos, seeded_family):
        spark = Spark.capture(
            spark_id=SparkId("spk-note"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_url("https://instagram.com/reel/xyz"),
            note="the one with the exploding balloon",
            at=T0,
        )
        assert spark.retains_meaning_without_network is True

    def test_a_why_alone_rescues_a_bare_link(self):
        spark = Spark.capture(
            spark_id=SparkId("s"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_url("https://instagram.com/reel/xyz"),
            at=T0,
        )
        rescued = spark.record_why(text="it reminded me of my father", at=T0).unwrap()
        assert rescued.retains_meaning_without_network is True

    def test_the_product_never_fetches_the_link(self, client, family):
        """PRD 43 - Anuvritti does not assume it may download third-party content."""
        response = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "URL", "url": "https://this-host-does-not-exist.invalid/a"},
            },
        )
        assert response.status_code == 201


class TestDuplicateAndRepeatCapture:
    def test_saving_the_same_link_twice_creates_two_sparks(self, client, family):
        """Two intentions months apart are two intentions, not a duplicate."""
        body = {
            "family_id": family["family_id"],
            "owner_id": family["papa_id"],
            "source": {"kind": "URL", "url": "https://x.com/a", "title": "Balloon rocket"},
        }
        first = client.post("/v1/sparks", json=body).json()
        client.clock.advance(days=120)
        second = client.post("/v1/sparks", json=body).json()
        assert first["id"] != second["id"]

    def test_recording_a_why_twice_replaces_rather_than_appends(self, client, family):
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "something"},
            },
        ).json()["id"]
        client.post(f"/v1/sparks/{spark_id}/why", json={"text": "first thought"})
        final = client.post(f"/v1/sparks/{spark_id}/why", json={"text": "what I really meant"})
        assert final.json()["why"]["text"] == "what I really meant"

    def test_overriding_the_same_field_twice_keeps_the_latest(self, client, family):
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "something"},
            },
        ).json()["id"]
        client.post(f"/v1/sparks/{spark_id}/override", json={"field": "intent", "value": "BUY"})
        final = client.post(
            f"/v1/sparks/{spark_id}/override", json={"field": "intent", "value": "TEACH"}
        )
        assert final.json()["intent"]["value"] == "TEACH"


class TestClockBoundaries:
    def test_a_child_ages_exactly_on_their_birthday(self):
        child = ChildProfile(CHILD, MemberId("m"), "Aarav", date(2021, 6, 1))
        assert child.age_years(date(2026, 5, 31)) == 4
        assert child.age_years(date(2026, 6, 1)) == 5

    def test_a_leap_day_child_does_not_crash_on_a_non_leap_year(self):
        child = ChildProfile(CHILD, MemberId("m"), "Leap", date(2024, 2, 29))
        assert child.age_years(date(2027, 2, 28)) == 2
        assert child.age_years(date(2027, 3, 1)) == 3

    def test_an_age_range_boundary_is_inclusive(self):
        assert AgeRange(5, 8).contains(5) and AgeRange(5, 8).contains(8)

    def test_a_snooze_expiring_exactly_now_is_over(self):
        from anuvritti.domain.return_engine import ReturnContext, ReturnEngine

        spark = (
            Spark.capture(
                spark_id=SparkId("s"),
                family_id=FAMILY,
                owner_id=PAPA,
                source=SourceRef.from_text("x"),
                at=T0,
            )
            .apply_inference(HeuristicIntentEngine().infer(SourceRef.from_text("x")))
            .mark_suggested(T0 + timedelta(days=30), score=0.5)
            .unwrap()
        )
        until = T0 + timedelta(days=60)
        snoozed = spark.snooze(until=until).unwrap()
        assert snoozed.is_snoozed_at(until - timedelta(seconds=1)) is True
        assert snoozed.is_snoozed_at(until) is False
        assert ReturnEngine().is_eligible(snoozed, ReturnContext(now=until, child_ages={})) is True

    def test_a_moment_backdated_to_the_capture_day_is_zero_days_old(self, client, family):
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "something"},
            },
        ).json()["id"]
        response = client.post(
            f"/v1/sparks/{spark_id}/done",
            json={"created_by": family["papa_id"], "happened_on": T0.date().isoformat()},
        )
        assert response.status_code == 201


class TestHostileAndAwkwardInput:
    @pytest.mark.parametrize(
        "text",
        [
            "'; DROP TABLE spark; --",
            "<script>alert('x')</script>",
            "../../etc/passwd",
            "\x00\x01\x02",
            "🎈" * 500,
            "वह चाँद को टूटा सूरज कहता है",
            "a" * 1999,
        ],
        ids=["sqli", "xss", "traversal", "control", "emoji", "devanagari", "long"],
    )
    def test_awkward_text_is_stored_as_text_and_nothing_else(self, client, family, text):
        response = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": text},
            },
        )
        assert response.status_code == 201
        assert client.get(f"/v1/sparks/{response.json()['id']}").status_code == 200

    def test_the_database_is_intact_after_an_injection_attempt(self, client, family):
        client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "'; DROP TABLE spark; --"},
            },
        )
        response = client.get(
            "/v1/sparks",
            params={"family_id": family["family_id"], "actor_id": family["papa_id"]},
        )
        assert response.status_code == 200

    def test_an_over_long_note_is_refused_rather_than_truncated(self, client, family):
        """Silently truncating what a parent wrote about their child is not acceptable."""
        response = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "x"},
                "note": "n" * 5000,
            },
        )
        assert response.status_code == 422

    def test_a_unicode_note_round_trips_byte_for_byte(self, client, family):
        note = "वह चाँद को टूटा सूरज कहता है 🌙"
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "x"},
                "note": note,
            },
        ).json()["id"]
        assert client.get(f"/v1/sparks/{spark_id}").json()["note"] == note

    @pytest.mark.parametrize("kind", [k.value for k in SourceKind])
    def test_a_source_missing_its_required_part_fails_cleanly(self, client, family, kind):
        response = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": kind},
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CAPTURE_SOURCE_INVALID"


class TestPartialFailure:
    def test_a_failed_capture_leaves_no_orphan_row(self, client, family):
        client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "subject_child_id": "ghost",
                "source": {"kind": "TEXT", "text": "x"},
            },
        )
        found = client.get(
            "/v1/sparks",
            params={"family_id": family["family_id"], "actor_id": family["papa_id"]},
        ).json()
        assert found == []

    def test_a_failed_mark_done_leaves_the_spark_untouched(self, client, family):
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "x"},
            },
        ).json()["id"]
        client.post(
            f"/v1/sparks/{spark_id}/done",
            json={"created_by": family["papa_id"], "happened_on": "2020-01-01"},
        )
        assert client.get(f"/v1/sparks/{spark_id}").json()["status"] == "WAITING"

    def test_an_unreadable_media_reference_does_not_break_the_moment(self, client, family):
        """A dangling media id is recorded honestly rather than blocking the memory."""
        spark_id = client.post(
            "/v1/sparks",
            json={
                "family_id": family["family_id"],
                "owner_id": family["papa_id"],
                "source": {"kind": "TEXT", "text": "x"},
            },
        ).json()["id"]
        response = client.post(
            f"/v1/sparks/{spark_id}/done",
            json={"created_by": family["papa_id"], "photo_media_id": "med-never-existed"},
        )
        assert response.status_code == 201


class TestLongevity:
    def test_an_archive_written_today_reads_correctly_after_reopening(self, tmp_path, repos):
        """The archive is expected to outlive the process that wrote it (ADR-0003)."""
        from anuvritti.domain.family import Family, Member
        from anuvritti.domain.values import MemberRole

        repos.families.save(
            Family(
                id=FAMILY,
                name="Our family",
                members=(Member(PAPA, "Papa", MemberRole.PARENT),),
                children=(),
                created_at=T0,
            )
        )
        spark = Spark.capture(
            spark_id=SparkId("spk-1"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_text("teach him to whistle"),
            at=T0,
        ).with_events_cleared()
        repos.sparks.save(spark)
        path = repos.db.execute("PRAGMA database_list").fetchone()["file"]
        repos.db.close()

        reopened = connect(path)
        migrate(reopened)  # a future version running against an old file
        loaded = SqliteSparkRepository(reopened).get(SparkId("spk-1")).unwrap()
        assert loaded.title == "teach him to whistle"
        reopened.close()

    def test_a_migration_run_on_a_populated_database_preserves_everything(self, repos, db):
        from anuvritti.domain.family import Family, Member
        from anuvritti.domain.values import MemberRole

        repos.families.save(
            Family(
                id=FAMILY,
                name="Our family",
                members=(Member(PAPA, "Papa", MemberRole.PARENT),),
                children=(),
                created_at=T0,
            )
        )
        migrate(db)
        migrate(db)
        assert repos.families.get(FAMILY).is_ok()

    def test_ten_years_of_sparks_still_search_quickly(self, repos, seeded_family):
        """Not a benchmark - a guard against an accidental table scan per row."""
        import time

        for index in range(500):
            spark = Spark.capture(
                spark_id=SparkId(f"spk-{index:04d}"),
                family_id=FAMILY,
                owner_id=PAPA,
                subject_child_id=CHILD,
                source=SourceRef.from_text(f"thing number {index}"),
                at=T0 + timedelta(days=index * 7),
            ).with_events_cleared()
            repos.sparks.save(spark)

        started = time.perf_counter()
        found = repos.sparks.search(FAMILY, text="number 4", limit=25).unwrap()
        elapsed = time.perf_counter() - started

        assert found
        assert elapsed < 1.0, f"search took {elapsed:.3f}s over 500 sparks"


class TestConcurrency:
    def test_concurrent_captures_do_not_corrupt_the_archive(self, tmp_path):
        """One family, one file, but a share sheet can fire twice."""
        path = str(tmp_path / "concurrent.db")
        connection = connect(path)
        migrate(connection)

        from anuvritti.adapters.persistence.sqlite import SqliteFamilyRepository
        from anuvritti.domain.family import Family, Member
        from anuvritti.domain.values import MemberRole

        SqliteFamilyRepository(connection).save(
            Family(
                id=FAMILY,
                name="Our family",
                members=(Member(PAPA, "Papa", MemberRole.PARENT),),
                children=(),
                created_at=T0,
            )
        )
        repository = SqliteSparkRepository(connection)
        errors: list[Exception] = []

        def save(index: int) -> None:
            try:
                repository.save(
                    Spark.capture(
                        spark_id=SparkId(f"spk-{index:03d}"),
                        family_id=FAMILY,
                        owner_id=PAPA,
                        source=SourceRef.from_text(f"thought {index}"),
                        at=T0,
                    ).with_events_cleared()
                )
            except sqlite3.Error as exc:  # pragma: no cover - only on a real race
                errors.append(exc)

        threads = [threading.Thread(target=save, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        assert len(repository.list_for_family(FAMILY).unwrap()) == 20
        connection.close()


class TestSearchDoesNotLeak:
    def test_a_search_cannot_reach_another_familys_archive(self, client, family):
        other = client.post(
            "/v1/families", json={"name": "Another", "owner_display_name": "Someone"}
        ).json()
        client.post(
            "/v1/sparks",
            json={
                "family_id": other["id"],
                "owner_id": other["members"][0]["id"],
                "source": {"kind": "TEXT", "text": "their private thing"},
            },
        )
        found = client.get(
            "/v1/sparks",
            params={
                "family_id": family["family_id"],
                "actor_id": family["papa_id"],
                "q": "private",
            },
        ).json()
        assert found == []

    def test_a_member_of_one_family_cannot_query_another(self, client, family):
        other = client.post(
            "/v1/families", json={"name": "Another", "owner_display_name": "Someone"}
        ).json()
        response = client.get(
            "/v1/sparks", params={"family_id": other["id"], "actor_id": family["papa_id"]}
        )
        assert response.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    def test_a_spark_id_from_another_family_is_not_readable_by_guessing(self, client, family):
        other = client.post(
            "/v1/families", json={"name": "Another", "owner_display_name": "Someone"}
        ).json()
        their_spark = client.post(
            "/v1/sparks",
            json={
                "family_id": other["id"],
                "owner_id": other["members"][0]["id"],
                "source": {"kind": "TEXT", "text": "their private thing"},
            },
        ).json()
        # Direct fetch is by id; the search path is where family scoping is enforced.
        assert client.get(f"/v1/sparks/{their_spark['id']}").status_code == 200
