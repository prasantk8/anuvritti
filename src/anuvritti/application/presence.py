"""Little Things and Right Now (PRD 17, 18, 48 F8-F9).

The two lowest-friction features in the product. Little Things is one tap and no
structure; Right Now is one question a day that a parent can answer in a sentence.

Neither has a streak, a target or a completion rate. They exist to catch what would
otherwise be lost, not to be kept up with (PRD 8.5).
"""

from __future__ import annotations

from dataclasses import dataclass

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    LittleThingRepository,
    RightNowRepository,
    UnitOfWork,
)
from anuvritti.domain.presence import LittleThing, RightNowSnapshot
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    IdGenerator,
    LittleThingId,
    MemberId,
    RightNowId,
)
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class CaptureLittleThingCommand:
    family_id: FamilyId
    author_id: MemberId
    subject_child_id: ChildId | None = None
    text: str | None = None
    audio_media_id: str | None = None


class CaptureLittleThingUseCase:
    """PRD 17 - one-tap capture. No title, no category, no form."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        little_things: LittleThingRepository,
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._little_things = little_things
        self._events = events
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def execute(self, command: CaptureLittleThingCommand) -> Result[LittleThing, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())

        permitted = family_result.unwrap().can_capture_for(
            command.author_id, command.subject_child_id
        )
        if permitted.is_err():
            return Err(permitted.unwrap_err())

        created = LittleThing.capture(
            little_thing_id=LittleThingId(self._ids.new_id()),
            family_id=command.family_id,
            author_id=command.author_id,
            subject_child_id=command.subject_child_id,
            text=command.text,
            audio_media_id=command.audio_media_id,
            at=self._clock.now(),
        )
        if created.is_err():
            return Err(created.unwrap_err())

        thing = created.unwrap()
        with self._uow:
            saved = self._little_things.save(thing)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(thing.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(thing)


@dataclass(frozen=True, slots=True)
class CaptureRightNowCommand:
    family_id: FamilyId
    child_id: ChildId
    answer: str
    prompt: str | None = None


class CaptureRightNowUseCase:
    """PRD 18 - an occasional micro-snapshot of who this child is at the moment.

    The prompt rotates daily and is chosen by the system, so answering never starts with
    "what should I write about?".
    """

    def __init__(
        self,
        *,
        families: FamilyRepository,
        right_now: RightNowRepository,
        events: EventPublisher,
        clock: Clock,
        ids: IdGenerator,
        uow: UnitOfWork,
    ) -> None:
        self._families = families
        self._right_now = right_now
        self._events = events
        self._clock = clock
        self._ids = ids
        self._uow = uow

    def todays_prompt(self) -> str:
        return RightNowSnapshot.prompt_for(self._clock.today())

    def execute(self, command: CaptureRightNowCommand) -> Result[RightNowSnapshot, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())

        child_result = family_result.unwrap().child(command.child_id)
        if child_result.is_err():
            return Err(child_result.unwrap_err())

        created = RightNowSnapshot.capture(
            right_now_id=RightNowId(self._ids.new_id()),
            family_id=command.family_id,
            child_id=command.child_id,
            prompt=command.prompt or self.todays_prompt(),
            answer=command.answer,
            at=self._clock.now(),
        )
        if created.is_err():
            return Err(created.unwrap_err())

        snapshot = created.unwrap()
        with self._uow:
            saved = self._right_now.save(snapshot)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(snapshot.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(snapshot)
