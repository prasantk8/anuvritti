"""TASK-215 - export everything, delete everything (PRD 44, 45).

The PRD lists these beside encryption, not beside settings. These tests treat them the
same way: a family that asks for their archive gets all of it, and a family that asks to
be forgotten leaves nothing behind on disk.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.sqlite import SqliteMediaCatalogue
from anuvritti.application.capture import (
    CaptureSparkCommand,
    CaptureSparkUseCase,
    RecordWhyCommand,
    RecordWhyUseCase,
)
from anuvritti.application.moments import MarkAsDoneCommand, MarkAsDoneUseCase
from anuvritti.application.presence import (
    CaptureLittleThingCommand,
    CaptureLittleThingUseCase,
    CaptureRightNowCommand,
    CaptureRightNowUseCase,
)
from anuvritti.application.privacy import (
    DeleteFamilyDataCommand,
    DeleteFamilyDataUseCase,
    ExportFamilyDataQuery,
    ExportFamilyDataUseCase,
)
from anuvritti.config.settings import DEFAULT_ALLOWED_MEDIA_TYPES
from anuvritti.domain.values import SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import ErrorCode
from anuvritti.shared.identity import FamilyId, SequentialIdGenerator
from tests.integration.conftest import CHILD, FAMILY, PAPA

T0 = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
PHOTO = b"\xff\xd8\xff\xe0" + b"his face" * 40


@pytest.fixture
def world(tmp_path: Path, repos, seeded_family):
    """A small but complete family archive: sparks, a why, a moment, media, presence."""

    class World:
        def __init__(self) -> None:
            self.tmp_path = tmp_path
            self.repos = repos
            self.clock = FrozenClock(T0)
            self.media = EncryptedFilesystemMediaStore(
                root=tmp_path / "media",
                catalogue=SqliteMediaCatalogue(repos.db),
                ids=SequentialIdGenerator("med"),
                encryption_key=Fernet.generate_key().decode(),
                max_bytes=1024 * 1024,
                allowed_mime_types=DEFAULT_ALLOWED_MEDIA_TYPES,
            )
            self.export = ExportFamilyDataUseCase(
                families=repos.families,
                sparks=repos.sparks,
                moments=repos.moments,
                little_things=repos.little_things,
                right_now=repos.right_now,
                media=self.media,
                events=repos.events,
                clock=self.clock,
            )
            self.delete = DeleteFamilyDataUseCase(
                families=repos.families,
                sparks=repos.sparks,
                moments=repos.moments,
                little_things=repos.little_things,
                right_now=repos.right_now,
                media=self.media,
                events=repos.events,
                clock=self.clock,
                uow=repos.uow,
            )
            self._seed()

        def _seed(self) -> None:
            capture = CaptureSparkUseCase(
                families=self.repos.families,
                sparks=self.repos.sparks,
                intent_engine=HeuristicIntentEngine(),
                events=self.repos.events,
                clock=self.clock,
                ids=SequentialIdGenerator("spk"),
                uow=self.repos.uow,
            )
            self.spark = capture.execute(
                CaptureSparkCommand(
                    family_id=FAMILY,
                    owner_id=PAPA,
                    subject_child_id=CHILD,
                    source=SourceRef.from_url(
                        "https://instagram.com/reel/abc",
                        creator="@sciencedad",
                        title="Balloon rocket experiment for ages 5-8",
                    ),
                    note="he will love this",
                )
            ).unwrap()
            self.other = capture.execute(
                CaptureSparkCommand(
                    family_id=FAMILY,
                    owner_id=PAPA,
                    source=SourceRef.from_text("teach him to whistle"),
                )
            ).unwrap()

            RecordWhyUseCase(
                sparks=self.repos.sparks,
                events=self.repos.events,
                clock=self.clock,
                uow=self.repos.uow,
            ).execute(
                RecordWhyCommand(spark_id=self.spark.id, text="I never had one growing up")
            ).unwrap()

            self.photo = self.media.put(
                FAMILY, content=PHOTO, mime_type="image/jpeg", at=T0
            ).unwrap()

            done_clock = FrozenClock(T0 + timedelta(days=243))
            self.moment = (
                MarkAsDoneUseCase(
                    sparks=self.repos.sparks,
                    moments=self.repos.moments,
                    events=self.repos.events,
                    clock=done_clock,
                    ids=SequentialIdGenerator("mom"),
                    uow=self.repos.uow,
                )
                .execute(
                    MarkAsDoneCommand(
                        spark_id=self.spark.id,
                        created_by=PAPA,
                        reflection="He laughed until he fell over.",
                        photo_media_id=str(self.photo.id),
                    )
                )
                .unwrap()
            )

            CaptureLittleThingUseCase(
                families=self.repos.families,
                little_things=self.repos.little_things,
                events=self.repos.events,
                clock=self.clock,
                ids=SequentialIdGenerator("lt"),
                uow=self.repos.uow,
            ).execute(
                CaptureLittleThingCommand(
                    family_id=FAMILY,
                    author_id=PAPA,
                    subject_child_id=CHILD,
                    text="He called the moon a broken sun.",
                )
            ).unwrap()

            CaptureRightNowUseCase(
                families=self.repos.families,
                right_now=self.repos.right_now,
                events=self.repos.events,
                clock=self.clock,
                ids=SequentialIdGenerator("rn"),
                uow=self.repos.uow,
            ).execute(
                CaptureRightNowCommand(
                    family_id=FAMILY, child_id=CHILD, answer="Volcanoes. Only volcanoes."
                )
            ).unwrap()

    return World()


class TestExportEverything:
    def test_the_archive_contains_every_kind_of_thing_the_family_created(self, world):
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        assert len(archive["sparks"]) == 2
        assert len(archive["moments"]) == 1
        assert len(archive["little_things"]) == 1
        assert len(archive["right_now"]) == 1
        assert len(archive["media_manifest"]) == 1

    def test_the_why_is_exported_because_it_is_the_point(self, world):
        """PRD 12 - this is the field that survives decades."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        whys = [s["why"]["text"] for s in archive["sparks"] if s["why"]]
        assert "I never had one growing up" in whys

    def test_ai_provenance_is_exported_so_a_guess_is_never_mistaken_for_a_fact(self, world):
        """PRD 8.7, 42 - the family gets to see what the machine invented."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        intent = archive["sparks"][0]["intent"]
        assert set(intent) == {"value", "source", "confidence", "human_override"}

    def test_the_source_context_is_exported_so_the_spark_outlives_the_link(self, world):
        """PRD 43 - the export must remain meaningful when the URL is dead."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        sources = [s["source"] for s in archive["sparks"]]
        assert any(s["creator"] == "@sciencedad" for s in sources)

    def test_children_are_exported_with_their_ages(self, world):
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        assert archive["family"]["children"][0]["display_name"] == "Aarav"
        assert archive["family"]["children"][0]["age_years"] == 4

    def test_the_manifest_indexes_media_without_embedding_the_bytes(self, world):
        """An export must not become a second, unencrypted copy of a child's photos."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        assert PHOTO not in json.dumps(archive).encode()
        assert archive["media_manifest"][0]["encrypted"] is True

    def test_the_archive_is_json_serialisable(self, world):
        """If it cannot be written to a file, it is not an export."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        assert json.loads(json.dumps(archive))["format_version"] == "1.0"

    def test_the_export_is_versioned_and_timestamped(self, world):
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        assert archive["format_version"]
        assert archive["exported_at"].startswith("2026-01-10")

    def test_exporting_is_audited(self, world):
        world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        names = [e["name"] for e in world.repos.events.raw_for_family(FAMILY)]
        assert "FamilyDataExported" in names

    def test_exporting_an_unknown_family_fails(self, world):
        result = world.export.execute(ExportFamilyDataQuery(FamilyId("nope")))
        assert result.unwrap_err().code is ErrorCode.FAMILY_NOT_FOUND

    def test_exporting_changes_nothing(self, world):
        before = len(world.repos.sparks.list_for_family(FAMILY).unwrap())
        world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        assert len(world.repos.sparks.list_for_family(FAMILY).unwrap()) == before


class TestDeleteEverything:
    def test_deletion_reports_what_it_removed(self, world):
        counts = world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        assert counts["sparks"] == 2
        assert counts["moments"] == 1
        assert counts["little_things"] == 1
        assert counts["right_now"] == 1
        assert counts["media"] == 1
        assert counts["family"] == 1

    def test_the_media_bytes_are_gone_from_disk(self, world):
        """PRD 44 - the bytes, not just the row."""
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        remaining = [p for p in (world.tmp_path / "media").rglob("*") if p.is_file()]
        assert remaining == []

    def test_nothing_of_the_family_remains_in_the_database(self, world):
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        assert world.repos.sparks.list_for_family(FAMILY).unwrap() == []
        assert world.repos.moments.list_for_family(FAMILY).unwrap() == []
        assert world.repos.little_things.list_for_family(FAMILY).unwrap() == []
        assert world.repos.right_now.list_for_family(FAMILY).unwrap() == []
        assert world.repos.families.get(FAMILY).is_err()

    def test_no_trace_of_the_childs_words_survives_anywhere(self, world):
        """The strongest form of the test: grep the whole database file."""
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        world.repos.db.execute("VACUUM")
        db_path = world.repos.db.execute("PRAGMA database_list").fetchone()["file"]
        raw = Path(db_path).read_bytes()
        assert b"broken sun" not in raw
        assert b"I never had one growing up" not in raw
        assert b"Volcanoes" not in raw

    def test_the_erasure_itself_is_recorded(self, world):
        """PRD 44 - the one fact that must outlive the data is that it was erased."""
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        events = world.repos.events.raw_for_family(FAMILY)
        assert [e["name"] for e in events] == ["FamilyDataDeleted"]

    def test_the_erasure_record_contains_no_family_content(self, world):
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        payload = str(world.repos.events.raw_for_family(FAMILY)[0]["payload"])
        assert "broken sun" not in payload
        assert "Volcanoes" not in payload

    def test_deleting_an_unknown_family_fails_rather_than_pretending(self, world):
        result = world.delete.execute(DeleteFamilyDataCommand(FamilyId("nope")))
        assert result.unwrap_err().code is ErrorCode.FAMILY_NOT_FOUND

    def test_another_family_is_untouched(self, world):
        from anuvritti.domain.family import Family, Member
        from anuvritti.domain.values import MemberRole
        from anuvritti.shared.identity import MemberId

        other_id = FamilyId("fam-2")
        world.repos.families.save(
            Family(
                id=other_id,
                name="Another family",
                members=(Member(MemberId("mem-other"), "Someone", MemberRole.PARENT),),
                children=(),
                created_at=T0,
            )
        )
        theirs = world.media.put(other_id, content=b"ID3 theirs", mime_type="audio/mpeg", at=T0)

        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()

        assert world.repos.families.get(other_id).is_ok()
        assert world.media.get(theirs.unwrap().id).unwrap() == b"ID3 theirs"

    def test_export_then_delete_is_the_full_leaving_flow(self, world):
        """A family should be able to take their archive and go."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()

        assert len(archive["sparks"]) == 2
        assert world.repos.families.get(FAMILY).is_err()

    def test_deletion_is_not_a_soft_flag(self, world):
        """A hidden row is not a deleted row."""
        world.delete.execute(DeleteFamilyDataCommand(FAMILY)).unwrap()
        rows = world.repos.db.execute("SELECT COUNT(*) AS n FROM spark").fetchone()["n"]
        assert rows == 0


class TestIntentToMomentIsPreserved:
    def test_the_export_shows_which_intentions_became_real(self, world):
        """PRD 53 - the primary metric must be reconstructable from the archive alone."""
        archive = world.export.execute(ExportFamilyDataQuery(FAMILY)).unwrap()
        realised = {m["spark_id"] for m in archive["moments"]}
        assert str(world.spark.id) in realised
        assert str(world.other.id) not in realised
