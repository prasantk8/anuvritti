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
from anuvritti.adapters.intent.spoken import SpokenIntentEngine
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.media.measure import FfprobeAudioDurationMeasurer
from anuvritti.adapters.persistence.schema import GuardedConnection, connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteDeviceRepository,
    SqliteEventPublisher,
    SqliteFamilyRepository,
    SqliteIdempotencyStore,
    SqliteLexiconRepository,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqlitePairingRepository,
    SqliteRightNowRepository,
    SqliteSparkRepository,
    SqliteUnitOfWork,
    SqliteVoiceNoteRepository,
)
from anuvritti.adapters.transcription.local import LocalTranscriber, SpeechModel
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
from anuvritti.application.voice import (
    CorrectTranscriptUseCase,
    GetVoiceNoteUseCase,
    KeepVoiceNoteUseCase,
    ListVoiceNotesUseCase,
)
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
    lexicon: SqliteLexiconRepository
    voice_notes: SqliteVoiceNoteRepository
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
    keep_voice_note: KeepVoiceNoteUseCase
    correct_transcript: CorrectTranscriptUseCase
    list_voice_notes: ListVoiceNotesUseCase
    get_voice_note: GetVoiceNoteUseCase
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
    speech: SpeechModel | None = None,
) -> Container:
    """Wire the application.

    `clock`, `ids` and `random` are injectable so tests are deterministic. `random` is the
    one that must never be defaulted anywhere but here: a predictable source would make
    every device token in the family guessable.

    `speech` defaults to `None`, which means every recording is kept and none is indexed.
    That is the shipping configuration, not a stub: a wrong transcript is a plausible lie
    attached to a piece of family history, and the recording it belongs to loses nothing by
    being unindexed. A family that installs a local model passes it here and gets a search
    box; there is no setting that sends audio anywhere else, because there is no adapter
    that could (`adapters/transcription/local.py`).
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
    lexicon = SqliteLexiconRepository(connection)
    voice_notes = SqliteVoiceNoteRepository(connection)
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

    transcriber = LocalTranscriber(media=media, model=speech, clock=clock)

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
        lexicon=lexicon,
        voice_notes=voice_notes,
        media=media,
        events=events,
        uow=uow,
        devices=devices,
        pairings=pairings,
        idempotency=idempotency,
        capture_spark=CaptureSparkUseCase(
            families=families,
            sparks=sparks,
            # A decorator, not a replacement: captions still go through the engine built
            # for captions, and only a transcript gets the spoken layer (TASK-604).
            intent_engine=SpokenIntentEngine(HeuristicIntentEngine()),
            events=events,
            clock=clock,
            ids=ids,
            uow=uow,
            # What this family has already corrected, so the next capture starts from
            # their vocabulary rather than from general English (TASK-801).
            lexicon=lexicon,
        ),
        record_why=RecordWhyUseCase(sparks=sparks, events=events, clock=clock, uow=uow),
        override_field=OverrideFieldUseCase(
            sparks=sparks, events=events, uow=uow, clock=clock, lexicon=lexicon
        ),
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
        keep_voice_note=KeepVoiceNoteUseCase(
            families=families,
            media=media,
            duration_measurer=FfprobeAudioDurationMeasurer(),
            voice_notes=voice_notes,
            transcriber=transcriber,
            events=events,
            clock=clock,
            uow=uow,
        ),
        correct_transcript=CorrectTranscriptUseCase(
            voice_notes=voice_notes, events=events, clock=clock, uow=uow
        ),
        list_voice_notes=ListVoiceNotesUseCase(voice_notes=voice_notes),
        get_voice_note=GetVoiceNoteUseCase(voice_notes=voice_notes),
        export_family=ExportFamilyDataUseCase(
            families=families,
            sparks=sparks,
            moments=moments,
            little_things=little_things,
            right_now=right_now,
            voice_notes=voice_notes,
            # PRD 44 cuts both ways: a family's own vocabulary is theirs to take with
            # them, and theirs to destroy.
            lexicon=lexicon,
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
            voice_notes=voice_notes,
            # PRD 44 cuts both ways: a family's own vocabulary is theirs to take with
            # them, and theirs to destroy.
            lexicon=lexicon,
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
