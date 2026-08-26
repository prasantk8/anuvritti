"""TASK-304 - what happens when the archive itself fails.

Every use case writes through a repository that can fail: a full disk, a locked file, a
corrupt page. These are the paths where a family silently loses something, so they are
tested as carefully as the happy ones.

Two properties are asserted throughout:
  * the failure surfaces as an `Err`, never as a success or an exception, and
  * nothing is left half-written.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.application.capture import (
    CaptureSparkCommand,
    CaptureSparkUseCase,
    OverrideFieldCommand,
    OverrideFieldUseCase,
    RecordWhyCommand,
    RecordWhyUseCase,
)
from anuvritti.application.film import (
    CompileFilmUseCase,
    ComposeFilmCommand,
    ComposeFilmUseCase,
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
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.application.returning import (
    GetWorthBringingBackUseCase,
    RespondToSuggestionCommand,
    RespondToSuggestionUseCase,
    SuggestionResponse,
    WorthBringingBackQuery,
)
from anuvritti.application.vault import SearchVaultQuery, SearchVaultUseCase
from anuvritti.domain.moment import Moment
from anuvritti.domain.return_engine import ReturnEngine
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, SourceRef
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import MomentId, SequentialIdGenerator, SparkId
from anuvritti.shared.result import Err
from tests.support.fakes import (
    CHILD,
    FAMILY,
    PAPA,
    InMemoryFamilyRepository,
    InMemoryLittleThingRepository,
    InMemoryMediaStore,
    InMemoryMomentRepository,
    InMemoryRightNowRepository,
    InMemorySparkRepository,
    InMemoryVoiceNoteRepository,
    NullUnitOfWork,
    RecordingEventPublisher,
    build_family,
)

NOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
DISK_FULL = DomainError(ErrorCode.CONFLICT, "the archive could not be written")


def failing(target: object, method: str) -> object:
    """Return `target` with one method replaced by a store failure."""

    def fail(*_args: object, **_kwargs: object) -> Err[DomainError]:
        return Err(DISK_FULL)

    setattr(target, method, fail)
    return target


class TrackingUnitOfWork(NullUnitOfWork):
    """Records whether the transaction was rolled back."""

    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        self.committed = True


@pytest.fixture
def clock():
    return FrozenClock(NOW)


class TestCaptureFailures:
    def _use_case(self, sparks, uow):
        return CaptureSparkUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=sparks,
            intent_engine=HeuristicIntentEngine(),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("spk"),
            uow=uow,
        )

    def _command(self) -> CaptureSparkCommand:
        return CaptureSparkCommand(
            family_id=FAMILY,
            owner_id=PAPA,
            subject_child_id=CHILD,
            source=SourceRef.from_text("balloon rocket experiment"),
        )

    def test_a_failed_save_surfaces_as_an_error(self, clock):
        sparks = failing(InMemorySparkRepository(), "save")
        result = self._use_case(sparks, TrackingUnitOfWork()).execute(self._command())
        assert result.unwrap_err() is DISK_FULL

    def test_a_failed_save_rolls_the_transaction_back(self, clock):
        uow = TrackingUnitOfWork()
        self._use_case(failing(InMemorySparkRepository(), "save"), uow).execute(self._command())
        assert uow.rolled_back is True
        assert uow.committed is False

    def test_a_failed_save_publishes_no_events(self, clock):
        events = RecordingEventPublisher()
        use_case = CaptureSparkUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=failing(InMemorySparkRepository(), "save"),
            intent_engine=HeuristicIntentEngine(),
            events=events,
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("spk"),
            uow=TrackingUnitOfWork(),
        )
        use_case.execute(self._command())
        assert events.events == []


class TestWhyAndOverrideFailures:
    def _spark(self, sparks):
        capture = CaptureSparkUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=sparks,
            intent_engine=HeuristicIntentEngine(),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("spk"),
            uow=NullUnitOfWork(),
        )
        return capture.execute(
            CaptureSparkCommand(
                family_id=FAMILY, owner_id=PAPA, source=SourceRef.from_text("something")
            )
        ).unwrap()

    def test_a_failed_why_save_rolls_back_and_reports(self):
        sparks = InMemorySparkRepository()
        spark = self._spark(sparks)
        uow = TrackingUnitOfWork()
        use_case = RecordWhyUseCase(
            sparks=failing(sparks, "save"),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            uow=uow,
        )
        result = use_case.execute(RecordWhyCommand(spark_id=spark.id, text="because"))
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True

    def test_a_failed_override_save_rolls_back_and_reports(self):
        sparks = InMemorySparkRepository()
        spark = self._spark(sparks)
        uow = TrackingUnitOfWork()
        use_case = OverrideFieldUseCase(
            sparks=failing(sparks, "save"), events=RecordingEventPublisher(), uow=uow
        )
        result = use_case.execute(
            OverrideFieldCommand(spark_id=spark.id, field="intent", value=IntentType.BUY)
        )
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True

    def test_overriding_a_missing_spark_reports_not_found(self):
        use_case = OverrideFieldUseCase(
            sparks=InMemorySparkRepository(), events=RecordingEventPublisher(), uow=NullUnitOfWork()
        )
        result = use_case.execute(
            OverrideFieldCommand(spark_id=SparkId("nope"), field="intent", value=IntentType.BUY)
        )
        assert result.unwrap_err().code is ErrorCode.SPARK_NOT_FOUND


class TestVaultFailures:
    def test_a_failed_search_surfaces_rather_than_returning_nothing(self):
        """An empty result and a broken index must never look the same to the caller."""
        use_case = SearchVaultUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=failing(InMemorySparkRepository(), "search"),
            clock=FrozenClock(NOW),
        )
        result = use_case.execute(SearchVaultQuery(family_id=FAMILY, actor_id=PAPA))
        assert result.unwrap_err() is DISK_FULL

    def test_an_unknown_child_in_an_age_query_is_reported(self):
        from anuvritti.shared.identity import ChildId

        use_case = SearchVaultUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=InMemorySparkRepository(),
            clock=FrozenClock(NOW),
        )
        result = use_case.execute(
            SearchVaultQuery(
                family_id=FAMILY, actor_id=PAPA, child_id=ChildId("ghost"), use_child_age=True
            )
        )
        assert result.unwrap_err().code is ErrorCode.CHILD_NOT_FOUND


class TestReturnFailures:
    def _use_case(self, sparks, uow):
        return GetWorthBringingBackUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=sparks,
            engine=ReturnEngine(),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            uow=uow,
            threshold=0.0,
        )

    def test_a_failed_listing_surfaces(self):
        result = self._use_case(
            failing(InMemorySparkRepository(), "list_returnable"), TrackingUnitOfWork()
        ).execute(WorthBringingBackQuery(family_id=FAMILY, actor_id=PAPA))
        assert result.unwrap_err() is DISK_FULL

    def test_a_failed_save_while_marking_suggested_rolls_back(self):
        sparks = InMemorySparkRepository()
        CaptureSparkUseCase(
            families=InMemoryFamilyRepository(build_family()),
            sparks=sparks,
            intent_engine=HeuristicIntentEngine(),
            events=RecordingEventPublisher(),
            clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
            ids=SequentialIdGenerator("spk"),
            uow=NullUnitOfWork(),
        ).execute(
            CaptureSparkCommand(
                family_id=FAMILY,
                owner_id=PAPA,
                subject_child_id=CHILD,
                source=SourceRef.from_text("science experiment to do together"),
            )
        ).unwrap()

        uow = TrackingUnitOfWork()
        result = self._use_case(failing(sparks, "save"), uow).execute(
            WorthBringingBackQuery(family_id=FAMILY, actor_id=PAPA)
        )
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True

    def test_a_failed_response_save_rolls_back(self):
        sparks = InMemorySparkRepository()
        spark = (
            CaptureSparkUseCase(
                families=InMemoryFamilyRepository(build_family()),
                sparks=sparks,
                intent_engine=HeuristicIntentEngine(),
                events=RecordingEventPublisher(),
                clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
                ids=SequentialIdGenerator("spk"),
                uow=NullUnitOfWork(),
            )
            .execute(
                CaptureSparkCommand(
                    family_id=FAMILY, owner_id=PAPA, source=SourceRef.from_text("something")
                )
            )
            .unwrap()
        )
        sparks.save(spark.mark_suggested(NOW, score=0.6).unwrap())

        uow = TrackingUnitOfWork()
        use_case = RespondToSuggestionUseCase(
            sparks=failing(sparks, "save"),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            uow=uow,
        )
        result = use_case.execute(
            RespondToSuggestionCommand(spark.id, SuggestionResponse.LETS_DO_IT)
        )
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True


class TestMomentFailures:
    def _harness(self):
        sparks = InMemorySparkRepository()
        spark = (
            CaptureSparkUseCase(
                families=InMemoryFamilyRepository(build_family()),
                sparks=sparks,
                intent_engine=HeuristicIntentEngine(),
                events=RecordingEventPublisher(),
                clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
                ids=SequentialIdGenerator("spk"),
                uow=NullUnitOfWork(),
            )
            .execute(
                CaptureSparkCommand(
                    family_id=FAMILY, owner_id=PAPA, source=SourceRef.from_text("something")
                )
            )
            .unwrap()
        )
        return sparks, spark

    def test_a_failed_lookup_for_an_existing_moment_surfaces(self):
        sparks, spark = self._harness()
        use_case = MarkAsDoneUseCase(
            sparks=sparks,
            moments=failing(InMemoryMomentRepository(), "find_by_spark"),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("mom"),
            uow=TrackingUnitOfWork(),
        )
        result = use_case.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA))
        assert result.unwrap_err() is DISK_FULL

    def test_a_failed_spark_save_rolls_back_before_the_moment_is_written(self):
        sparks, spark = self._harness()
        moments = InMemoryMomentRepository()
        uow = TrackingUnitOfWork()
        use_case = MarkAsDoneUseCase(
            sparks=failing(sparks, "save"),
            moments=moments,
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("mom"),
            uow=uow,
        )
        result = use_case.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA))
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True
        assert moments.list_for_family(FAMILY).unwrap() == []

    def test_a_failed_moment_save_rolls_back_the_spark_transition(self):
        sparks, spark = self._harness()
        uow = TrackingUnitOfWork()
        use_case = MarkAsDoneUseCase(
            sparks=sparks,
            moments=failing(InMemoryMomentRepository(), "save"),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("mom"),
            uow=uow,
        )
        result = use_case.execute(MarkAsDoneCommand(spark_id=spark.id, created_by=PAPA))
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True


class TestPresenceFailures:
    def test_a_failed_little_thing_save_rolls_back(self):
        uow = TrackingUnitOfWork()
        use_case = CaptureLittleThingUseCase(
            families=InMemoryFamilyRepository(build_family()),
            little_things=failing(InMemoryLittleThingRepository(), "save"),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("lt"),
            uow=uow,
        )
        result = use_case.execute(
            CaptureLittleThingCommand(family_id=FAMILY, author_id=PAPA, text="something")
        )
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True

    def test_a_failed_right_now_save_rolls_back(self):
        uow = TrackingUnitOfWork()
        use_case = CaptureRightNowUseCase(
            families=InMemoryFamilyRepository(build_family()),
            right_now=failing(InMemoryRightNowRepository(), "save"),
            events=RecordingEventPublisher(),
            clock=FrozenClock(NOW),
            ids=SequentialIdGenerator("rn"),
            uow=uow,
        )
        result = use_case.execute(
            CaptureRightNowCommand(family_id=FAMILY, child_id=CHILD, answer="Volcanoes")
        )
        assert result.unwrap_err() is DISK_FULL
        assert uow.rolled_back is True


class TestPrivacyFailures:
    """PRD 44 - a partial export or a partial deletion is worse than a clear failure."""

    def _export(self, **overrides):
        parts = {
            "families": InMemoryFamilyRepository(build_family()),
            "sparks": InMemorySparkRepository(),
            "moments": InMemoryMomentRepository(),
            "little_things": InMemoryLittleThingRepository(),
            "right_now": InMemoryRightNowRepository(),
            "voice_notes": InMemoryVoiceNoteRepository(),
            "media": InMemoryMediaStore(),
        }
        parts.update(overrides)
        return ExportFamilyDataUseCase(
            events=RecordingEventPublisher(), clock=FrozenClock(NOW), **parts
        )

    @pytest.mark.parametrize(
        "part,factory,method",
        [
            ("sparks", InMemorySparkRepository, "list_for_family"),
            ("moments", InMemoryMomentRepository, "list_for_family"),
            ("little_things", InMemoryLittleThingRepository, "list_for_family"),
            ("right_now", InMemoryRightNowRepository, "list_for_family"),
            ("voice_notes", InMemoryVoiceNoteRepository, "list_for_family"),
            ("media", InMemoryMediaStore, "list_for_family"),
        ],
    )
    def test_a_partial_export_is_refused_rather_than_shipped(self, part, factory, method):
        use_case = self._export(**{part: failing(factory(), method)})
        assert use_case.execute(ExportFamilyDataQuery(FAMILY)).unwrap_err() is DISK_FULL

    def _delete(self, uow, **overrides):
        parts = {
            "families": InMemoryFamilyRepository(build_family()),
            "sparks": InMemorySparkRepository(),
            "moments": InMemoryMomentRepository(),
            "little_things": InMemoryLittleThingRepository(),
            "right_now": InMemoryRightNowRepository(),
            "voice_notes": InMemoryVoiceNoteRepository(),
            "media": InMemoryMediaStore(),
        }
        parts.update(overrides)
        return DeleteFamilyDataUseCase(
            events=RecordingEventPublisher(), clock=FrozenClock(NOW), uow=uow, **parts
        )

    def test_a_failed_media_deletion_stops_before_the_index_is_lost(self):
        """Losing the catalogue while keeping the files would orphan a child's photos."""
        uow = TrackingUnitOfWork()
        use_case = self._delete(uow, media=failing(InMemoryMediaStore(), "delete_for_family"))
        assert use_case.execute(DeleteFamilyDataCommand(FAMILY)).unwrap_err() is DISK_FULL
        assert uow.committed is False

    @pytest.mark.parametrize(
        "part,factory",
        [
            ("sparks", InMemorySparkRepository),
            ("moments", InMemoryMomentRepository),
            ("little_things", InMemoryLittleThingRepository),
            ("right_now", InMemoryRightNowRepository),
            ("voice_notes", InMemoryVoiceNoteRepository),
        ],
    )
    def test_a_failed_deletion_rolls_back(self, part, factory):
        uow = TrackingUnitOfWork()
        use_case = self._delete(uow, **{part: failing(factory(), "delete_for_family")})
        assert use_case.execute(DeleteFamilyDataCommand(FAMILY)).unwrap_err() is DISK_FULL
        assert uow.rolled_back is True

    def test_a_failed_family_row_deletion_rolls_back(self):
        uow = TrackingUnitOfWork()
        use_case = self._delete(
            uow, families=failing(InMemoryFamilyRepository(build_family()), "delete")
        )
        assert use_case.execute(DeleteFamilyDataCommand(FAMILY)).unwrap_err() is DISK_FULL
        assert uow.rolled_back is True


class TestFilmCompositionFailures:
    """TASK-705. A film is assembled by reading four stores, any of which can fail.

    The property that matters here is narrow and easy to lose: a read that fails must stop
    the composition. The alternative - skip the row and keep going - produces a film that is
    shorter than the year was, and looks exactly like a film of a quieter year.
    """

    def _moment(self, sparks: InMemorySparkRepository) -> InMemoryMomentRepository:
        spark = Spark.capture(
            spark_id=SparkId("spk-1"),
            family_id=FAMILY,
            owner_id=PAPA,
            source=SourceRef.from_text("skip stones at the lake"),
            at=NOW,
            subject_child_id=CHILD,
        )
        sparks.save(spark)
        moments = InMemoryMomentRepository()
        moments.save(
            Moment.create(
                moment_id=MomentId("mom-1"),
                family_id=FAMILY,
                spark_id=spark.id,
                created_by=PAPA,
                spark_captured_at=NOW,
                at=NOW,
            ).unwrap()
        )
        return moments

    def _stores(self, **overrides) -> dict:
        """One archive, shared by the composer and the verifier - only the fault differs."""
        sparks = overrides.pop("sparks", None) or InMemorySparkRepository()
        stores = {
            "families": InMemoryFamilyRepository(build_family()),
            "sparks": sparks,
            "moments": self._moment(sparks),
            "voice_notes": InMemoryVoiceNoteRepository(),
            "little_things": InMemoryLittleThingRepository(),
            "media": InMemoryMediaStore(),
            "ids": SequentialIdGenerator("film"),
        }
        stores.update(overrides)
        return stores

    def _compose(self, stores: dict) -> ComposeFilmUseCase:
        return ComposeFilmUseCase(**{k: v for k, v in stores.items() if k != "little_things"})

    def _verify(self, stores: dict, **overrides) -> VerifyProvenanceUseCase:
        parts = {
            "sparks": stores["sparks"],
            "moments": stores["moments"],
            "voice_notes": stores["voice_notes"],
            "little_things": stores["little_things"],
            "media": stores["media"],
            "clock": FrozenClock(NOW),
        }
        parts.update(overrides)
        return VerifyProvenanceUseCase(**parts)

    def _command(self) -> ComposeFilmCommand:
        return ComposeFilmCommand(family_id=FAMILY, actor_id=PAPA)

    def test_an_unreadable_moment_table_stops_the_film(self):
        stores = self._stores(moments=failing(InMemoryMomentRepository(), "list_for_family"))
        use_case = self._compose(stores)
        assert use_case.execute(self._command()).unwrap_err() is DISK_FULL

    def test_a_moment_whose_spark_cannot_be_read_stops_the_film(self):
        """Not "skip the scene". A scene missing its heading is a scene missing its meaning."""
        sparks = InMemorySparkRepository()
        stores = self._stores(sparks=failing(sparks, "get"), moments=self._moment(sparks))
        use_case = self._compose(stores)
        assert use_case.execute(self._command()).unwrap_err() is DISK_FULL

    def test_a_compiler_that_refuses_is_reported_and_not_papered_over(self):
        class RefusingCompiler:
            def compile(self, spec):
                return Err(DISK_FULL)

        stores = self._stores()
        use_case = CompileFilmUseCase(
            compose=self._compose(stores),
            verify=self._verify(stores),
            compiler=RefusingCompiler(),
        )
        assert use_case.execute(self._command()).unwrap_err() is DISK_FULL

    def test_an_archive_that_cannot_be_searched_is_not_reported_as_an_empty_archive(self):
        """The one distinction this whole checkpoint rests on.

        A repository that fails to answer is not a repository saying "no such Spark". If the
        second reading were allowed, an unreachable disk would write "MISSING" into a ledger
        whose entire job is to be believed, and the film would be refused for a reason that
        was never true.
        """

        class Silent:
            """Answers the composer, refuses the checker. Only the verification path fails."""

            def get(self, spark_id):
                return Err(DISK_FULL)

        stores = self._stores()
        use_case = CompileFilmUseCase(
            compose=self._compose(stores),
            verify=self._verify(stores, sparks=Silent()),
            compiler=FilmkitFilmCompiler(),
        )
        assert use_case.execute(self._command()).unwrap_err() is DISK_FULL
