"""Composition root.

The one place that knows every concrete adapter. Everything else receives its
dependencies. Swapping SQLite for Postgres, or the heuristic engine for an LLM, is a
change to this file and nothing else - which is the entire point of ADR-0001.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from anuvritti.adapters.intent.heuristic import HeuristicIntentEngine
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.schema import GuardedConnection, connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteDeviceRepository,
    SqliteEventPublisher,
    SqliteFamilyRepository,
    SqliteIdempotencyStore,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqlitePairingRepository,
    SqliteRightNowRepository,
    SqliteSparkRepository,
    SqliteUnitOfWork,
)
from anuvritti.application.access import (
    AuthenticateDeviceUseCase,
    ClaimPairingUseCase,
    ListDevicesUseCase,
    OpenPairingUseCase,
    PairDeviceUseCase,
    RevokeDeviceUseCase,
)
from anuvritti.application.capture import (
    CaptureSparkUseCase,
    OverrideFieldUseCase,
    RecordWhyUseCase,
)
from anuvritti.application.moments import MarkAsDoneUseCase
from anuvritti.application.presence import CaptureLittleThingUseCase, CaptureRightNowUseCase
from anuvritti.application.privacy import DeleteFamilyDataUseCase, ExportFamilyDataUseCase
from anuvritti.application.returning import (
    GetWorthBringingBackUseCase,
    RespondToSuggestionUseCase,
)
from anuvritti.application.vault import SearchVaultUseCase
from anuvritti.config.settings import Settings
from anuvritti.domain.access import CODE_TTL
from anuvritti.domain.return_engine import ReturnEngine
from anuvritti.shared.clock import Clock, SystemClock
from anuvritti.shared.identity import IdGenerator, Uuid7IdGenerator
from anuvritti.shared.randomness import RandomSource, SystemRandomSource


@dataclass
class Container:
    """Everything the HTTP layer is allowed to reach for."""

    settings: Settings
    connection: GuardedConnection
    clock: Clock
    ids: IdGenerator
    random: RandomSource
    pairing_ttl: timedelta

    families: SqliteFamilyRepository
    sparks: SqliteSparkRepository
    moments: SqliteMomentRepository
    little_things: SqliteLittleThingRepository
    right_now: SqliteRightNowRepository
    media: EncryptedFilesystemMediaStore
    events: SqliteEventPublisher
    uow: SqliteUnitOfWork
    devices: SqliteDeviceRepository
    pairings: SqlitePairingRepository
    idempotency: SqliteIdempotencyStore

    capture_spark: CaptureSparkUseCase
    record_why: RecordWhyUseCase
    override_field: OverrideFieldUseCase
    search_vault: SearchVaultUseCase
    worth_bringing_back: GetWorthBringingBackUseCase
    respond_to_suggestion: RespondToSuggestionUseCase
    mark_as_done: MarkAsDoneUseCase
    capture_little_thing: CaptureLittleThingUseCase
    capture_right_now: CaptureRightNowUseCase
    export_family: ExportFamilyDataUseCase
    delete_family: DeleteFamilyDataUseCase
    pair_device: PairDeviceUseCase
    open_pairing: OpenPairingUseCase
    claim_pairing: ClaimPairingUseCase
    authenticate_device: AuthenticateDeviceUseCase
    list_devices: ListDevicesUseCase
    revoke_device: RevokeDeviceUseCase

    def close(self) -> None:
        self.connection.close()


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    random: RandomSource | None = None,
) -> Container:
    """Wire the application.

    `clock`, `ids` and `random` are injectable so tests are deterministic. `random` is the
    one that must never be defaulted anywhere but here: a predictable source would make
    every device token in the family guessable.
    """
    clock = clock or SystemClock()
    ids = ids or Uuid7IdGenerator()
    random = random or SystemRandomSource()

    db_path = settings.db_path
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = connect(str(db_path))
    migrate(connection)

    families = SqliteFamilyRepository(connection)
    sparks = SqliteSparkRepository(connection)
    moments = SqliteMomentRepository(connection)
    little_things = SqliteLittleThingRepository(connection)
    right_now = SqliteRightNowRepository(connection)
    events = SqliteEventPublisher(connection)
    uow = SqliteUnitOfWork(connection)
    devices = SqliteDeviceRepository(connection)
    pairings = SqlitePairingRepository(connection)
    idempotency = SqliteIdempotencyStore(connection)
    media = EncryptedFilesystemMediaStore(
        root=Path(settings.media_dir),
        catalogue=SqliteMediaCatalogue(connection),
        ids=ids,
        encryption_key=settings.media_key,
        max_bytes=settings.max_media_bytes,
        allowed_mime_types=settings.allowed_media_types,
    )

    pair_device = PairDeviceUseCase(
        devices=devices, events=events, clock=clock, ids=ids, random=random, uow=uow
    )

    return Container(
        settings=settings,
        connection=connection,
        clock=clock,
        ids=ids,
        random=random,
        pairing_ttl=CODE_TTL,
        families=families,
        sparks=sparks,
        moments=moments,
        little_things=little_things,
        right_now=right_now,
        media=media,
        events=events,
        uow=uow,
        devices=devices,
        pairings=pairings,
        idempotency=idempotency,
        capture_spark=CaptureSparkUseCase(
            families=families,
            sparks=sparks,
            intent_engine=HeuristicIntentEngine(),
            events=events,
            clock=clock,
            ids=ids,
            uow=uow,
        ),
        record_why=RecordWhyUseCase(sparks=sparks, events=events, clock=clock, uow=uow),
        override_field=OverrideFieldUseCase(sparks=sparks, events=events, uow=uow),
        search_vault=SearchVaultUseCase(families=families, sparks=sparks, clock=clock),
        worth_bringing_back=GetWorthBringingBackUseCase(
            families=families,
            sparks=sparks,
            engine=ReturnEngine(),
            events=events,
            clock=clock,
            uow=uow,
            max_suggestions_per_day=settings.max_suggestions_per_day,
            threshold=settings.suggestion_threshold,
            maturation_horizon_days=settings.maturation_horizon_days,
            min_days_before_return=settings.min_days_before_return,
        ),
        respond_to_suggestion=RespondToSuggestionUseCase(
            sparks=sparks,
            events=events,
            clock=clock,
            uow=uow,
            snooze_cooldown_days=settings.snooze_cooldown_days,
        ),
        mark_as_done=MarkAsDoneUseCase(
            sparks=sparks, moments=moments, events=events, clock=clock, ids=ids, uow=uow
        ),
        capture_little_thing=CaptureLittleThingUseCase(
            families=families,
            little_things=little_things,
            events=events,
            clock=clock,
            ids=ids,
            uow=uow,
        ),
        capture_right_now=CaptureRightNowUseCase(
            families=families,
            right_now=right_now,
            events=events,
            clock=clock,
            ids=ids,
            uow=uow,
        ),
        export_family=ExportFamilyDataUseCase(
            families=families,
            sparks=sparks,
            moments=moments,
            little_things=little_things,
            right_now=right_now,
            media=media,
            events=events,
            clock=clock,
        ),
        delete_family=DeleteFamilyDataUseCase(
            families=families,
            sparks=sparks,
            moments=moments,
            little_things=little_things,
            right_now=right_now,
            media=media,
            events=events,
            clock=clock,
            uow=uow,
        ),
        pair_device=pair_device,
        open_pairing=OpenPairingUseCase(pairings=pairings, clock=clock, random=random, uow=uow),
        claim_pairing=ClaimPairingUseCase(
            pairings=pairings,
            families=families,
            pair_device=pair_device,
            clock=clock,
            uow=uow,
        ),
        authenticate_device=AuthenticateDeviceUseCase(devices=devices, clock=clock),
        list_devices=ListDevicesUseCase(devices=devices),
        revoke_device=RevokeDeviceUseCase(devices=devices, events=events, clock=clock, uow=uow),
    )
