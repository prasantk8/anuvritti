"""TASK-709: a child's birthday year is a complete, repeatable, truthful film."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmUseCase,
    TheYearCommand,
    TheYearUseCase,
)
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.domain.family import ChildProfile, Family
from anuvritti.domain.film import CitationKind, SceneKind
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import LittleThingId, MomentId, SequentialIdGenerator, SparkId
from tests.integration.conftest import db as db
from tests.integration.conftest import repos as repos
from tests.integration.conftest import seeded_family as seeded_family
from tests.support.fakes import CHILD, FAMILY, PAPA, InMemoryMediaStore, build_family


@pytest.fixture
def media_store() -> InMemoryMediaStore:
    return InMemoryMediaStore()


def _year(*, repos, media, child=CHILD) -> TheYearUseCase:
    compose = ComposeFilmUseCase(
        families=repos.families,
        sparks=repos.sparks,
        moments=repos.moments,
        voice_notes=repos.voice_notes,
        little_things=repos.little_things,
        media=media,
        ids=SequentialIdGenerator("film"),
    )
    verify = VerifyProvenanceUseCase(
        sparks=repos.sparks,
        moments=repos.moments,
        voice_notes=repos.voice_notes,
        little_things=repos.little_things,
        media=media,
        clock=FrozenClock(datetime(2026, 8, 26, tzinfo=UTC)),
    )
    return TheYearUseCase(
        families=repos.families,
        compile_film=CompileFilmUseCase(
            compose=compose, verify=verify, compiler=FilmkitFilmCompiler()
        ),
    )


def _moment(repos, *, name: str, on: date, child=CHILD) -> None:
    at = datetime.combine(on, datetime.min.time(), tzinfo=UTC)
    spark = Spark.capture(
        spark_id=SparkId(f"spark-{name}"),
        family_id=FAMILY,
        owner_id=PAPA,
        source=SourceRef.from_text(name),
        at=at,
        subject_child_id=child,
    )
    repos.sparks.save(spark).unwrap()
    repos.moments.save(
        Moment.create(
            moment_id=MomentId(f"moment-{name}"),
            family_id=FAMILY,
            spark_id=spark.id,
            created_by=PAPA,
            spark_captured_at=at,
            at=at,
            happened_on=on,
        ).unwrap()
    ).unwrap()


def _little(repos, *, name: str, on: date, child=CHILD) -> None:
    repos.little_things.save(
        LittleThing.capture(
            little_thing_id=LittleThingId(f"little-{name}"),
            family_id=FAMILY,
            author_id=PAPA,
            subject_child_id=child,
            text=name,
            at=datetime.combine(on, datetime.min.time(), tzinfo=UTC),
        ).unwrap()
    ).unwrap()


def test_the_year_runs_from_one_birthday_through_the_day_before_the_next(
    repos, seeded_family, media_store
):
    _moment(repos, name="before", on=date(2024, 5, 31))
    _moment(repos, name="birthday", on=date(2024, 6, 1))
    _little(repos, name="small words", on=date(2025, 5, 31))
    _moment(repos, name="next birthday", on=date(2025, 6, 1))

    package = (
        _year(repos=repos, media=media_store)
        .execute(
            TheYearCommand(family_id=FAMILY, actor_id=PAPA, child_id=CHILD, birthday_year=2024)
        )
        .unwrap()
    )

    evidence = [scene for scene in package.spec.scenes if scene.kind.is_evidence]
    assert [scene.heading for scene in evidence] == ["birthday", "A little thing"]
    assert evidence[1].body == "small words"
    assert evidence[1].kind is SceneKind.LITTLE_THING
    assert evidence[1].cites[0].kind is CitationKind.LITTLE_THING
    assert package.provenance.is_clean


def test_the_same_child_and_birthday_year_have_one_stable_film_identity(
    repos, seeded_family, media_store
):
    _moment(repos, name="garden", on=date(2024, 7, 2))
    command = TheYearCommand(family_id=FAMILY, actor_id=PAPA, child_id=CHILD, birthday_year=2024)

    first = _year(repos=repos, media=media_store).execute(command).unwrap()
    second = _year(repos=repos, media=media_store).execute(command).unwrap()

    assert first.spec.id == second.spec.id == "the-year-ch-1-2024"
    assert first.spec.title == second.spec.title == "Aarav, 2024-2025"


def test_a_leap_day_childs_non_leap_year_begins_on_march_first(repos, seeded_family, media_store):
    family = build_family()
    leap_child = ChildProfile(CHILD, family.children[0].member_id, "Aarav", date(2020, 2, 29))
    repos.families.save(
        Family(
            id=family.id,
            name=family.name,
            members=family.members,
            children=(leap_child,),
            created_at=family.created_at,
        )
    ).unwrap()
    _moment(repos, name="too soon", on=date(2025, 2, 28))
    _moment(repos, name="new year", on=date(2025, 3, 1))

    package = (
        _year(repos=repos, media=media_store)
        .execute(
            TheYearCommand(family_id=FAMILY, actor_id=PAPA, child_id=CHILD, birthday_year=2025)
        )
        .unwrap()
    )

    assert [s.heading for s in package.spec.scenes if s.kind.is_evidence] == ["new year"]


def test_only_opening_and_closing_may_exist_without_a_real_source(
    repos, seeded_family, media_store
):
    _moment(repos, name="treehouse", on=date(2024, 6, 1))
    _little(repos, name="called every ladder a mountain", on=date(2024, 6, 2))

    package = (
        _year(repos=repos, media=media_store)
        .execute(
            TheYearCommand(family_id=FAMILY, actor_id=PAPA, child_id=CHILD, birthday_year=2024)
        )
        .unwrap()
    )

    assert package.spec.scenes[0].kind is SceneKind.OPENING
    assert package.spec.scenes[-1].kind is SceneKind.CLOSING
    assert all(scene.cites for scene in package.spec.scenes[1:-1])
    assert all(entry.status.value == "VERIFIED" for entry in package.provenance.entries)
