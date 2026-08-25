"""Shared fixtures for integration tests - real SQLite, real filesystem."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import GuardedConnection, connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteEventPublisher,
    SqliteFamilyRepository,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqliteRightNowRepository,
    SqliteSparkRepository,
    SqliteUnitOfWork,
    SqliteVoiceNoteRepository,
)
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.values import MemberRole
from anuvritti.shared.identity import ChildId, FamilyId, MemberId

FAMILY = FamilyId("fam-1")
PAPA = MemberId("mem-papa")
CHILD = ChildId("ch-1")


@pytest.fixture
def db(tmp_path: Path) -> GuardedConnection:
    connection = connect(str(tmp_path / "anuvritti.db"))
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def repos(db: GuardedConnection):
    class Repos:
        def __init__(self) -> None:
            self.db = db
            self.families = SqliteFamilyRepository(db)
            self.sparks = SqliteSparkRepository(db)
            self.moments = SqliteMomentRepository(db)
            self.little_things = SqliteLittleThingRepository(db)
            self.right_now = SqliteRightNowRepository(db)
            self.voice_notes = SqliteVoiceNoteRepository(db)
            self.media_catalogue = SqliteMediaCatalogue(db)
            self.events = SqliteEventPublisher(db)
            self.uow = SqliteUnitOfWork(db)

    return Repos()


@pytest.fixture
def seeded_family(repos) -> Family:
    family = Family(
        id=FAMILY,
        name="Our family",
        members=(Member(PAPA, "Papa", MemberRole.PARENT),),
        children=(ChildProfile(CHILD, MemberId("mem-son"), "Aarav", date(2021, 6, 1)),),
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    repos.families.save(family)
    return family
