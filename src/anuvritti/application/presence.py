"""Little Things and Right Now (PRD 17, 18, 48 F8-F9).

The two lowest-friction features in the product. Little Things is one tap and no
structure; Right Now is one question a day that a parent can answer in a sentence.

Neither has a streak, a target or a completion rate. They exist to catch what would
otherwise be lost, not to be kept up with (PRD 8.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from anuvritti.application.ports import (
    EventPublisher,
    FamilyRepository,
    LittleThingRepository,
    RightNowRepository,
    SparkRepository,
    UnitOfWork,
)
from anuvritti.domain.presence import (
    LittleThing,
    RightNowMilestone,
    RightNowSnapshot,
)
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import IntentType, MemberRole, SourceRef
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    IdGenerator,
    LittleThingId,
    MemberId,
    RightNowId,
    SparkId,
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
    author_id: MemberId | None = None


class CaptureRightNowUseCase:
    """PRD 18 - an occasional micro-snapshot of who this child is at the moment.

    The prompt rotates daily and is chosen by the system, so answering never starts with
    "what should I write about?".

    TASK-811: An answer to "What question did he ask that you could not answer?" automatically
    becomes a TELL Spark with no extra tap required.
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
        sparks: SparkRepository | None = None,
    ) -> None:
        self._families = families
        self._right_now = right_now
        self._events = events
        self._clock = clock
        self._ids = ids
        self._uow = uow
        self._sparks = sparks

    def todays_prompt(self) -> str:
        return RightNowSnapshot.prompt_for(self._clock.today())

    def execute(self, command: CaptureRightNowCommand) -> Result[RightNowSnapshot, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())

        child_result = family_result.unwrap().child(command.child_id)
        if child_result.is_err():
            return Err(child_result.unwrap_err())

        prompt_text = command.prompt or self.todays_prompt()
        created = RightNowSnapshot.capture(
            right_now_id=RightNowId(self._ids.new_id()),
            family_id=command.family_id,
            child_id=command.child_id,
            prompt=prompt_text,
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

            # TASK-811: "Ask Papa, later" - auto-create TELL spark for unanswerable question prompt
            if (
                "question did he ask" in prompt_text.lower()
                or "question did she ask" in prompt_text.lower()
            ) and self._sparks is not None:
                fam = family_result.unwrap()
                parents = [m for m in fam.members if m.role.is_parent]
                author_id = command.author_id or (parents[0].id if parents else fam.members[0].id)
                child_name = child_result.unwrap().display_name
                spark = Spark.capture(
                    spark_id=SparkId(self._ids.new_id()),
                    family_id=command.family_id,
                    owner_id=author_id,
                    subject_child_id=command.child_id,
                    source=SourceRef.from_text(
                        snapshot.answer,
                        title=f"Question from {child_name}: {snapshot.answer}",
                    ),
                    at=self._clock.now(),
                )
                overridden = spark.override_intent(IntentType.TELL)
                if overridden.is_ok():
                    self._sparks.save(overridden.unwrap())

            self._events.publish(snapshot.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(snapshot)


@dataclass(frozen=True, slots=True)
class CaptureRightNowMilestoneCommand:
    """TASK-817: Multi-field snapshot capturing several dimensions at once."""

    family_id: FamilyId
    child_id: ChildId
    obsessions: str = ""
    funny_words: str = ""
    favorite_things: str = ""
    interests: tuple[str, ...] = ()
    difficult_questions: str = ""
    notes: str = ""


class CaptureRightNowMilestoneUseCase:
    """TASK-817: Periodic snapshot capturing multiple fields without habit pressure."""

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

    def execute(
        self, command: CaptureRightNowMilestoneCommand
    ) -> Result[RightNowMilestone, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())

        child_result = family_result.unwrap().child(command.child_id)
        if child_result.is_err():
            return Err(child_result.unwrap_err())

        created = RightNowMilestone.capture(
            milestone_id=RightNowId(self._ids.new_id()),
            family_id=command.family_id,
            child_id=command.child_id,
            at=self._clock.now(),
            obsessions=command.obsessions,
            funny_words=command.funny_words,
            favorite_things=command.favorite_things,
            interests=command.interests,
            difficult_questions=command.difficult_questions,
            notes=command.notes,
        )
        if created.is_err():
            return Err(created.unwrap_err())

        milestone = created.unwrap()
        # Save summary in right_now repo as snapshot representation
        summary = (
            f"Obsessions: {milestone.obsessions}; "
            f"Words: {milestone.funny_words}; "
            f"Favorites: {milestone.favorite_things}"
        )
        rep_snapshot = RightNowSnapshot(
            id=milestone.id,
            family_id=milestone.family_id,
            child_id=milestone.child_id,
            prompt="Right Now Milestone Snapshot",
            answer=summary,
            captured_at=milestone.captured_at,
            pending_events=milestone.pending_events,
        )
        with self._uow:
            saved = self._right_now.save(rep_snapshot)
            if saved.is_err():
                self._uow.rollback()
                return Err(saved.unwrap_err())
            self._events.publish(milestone.pending_events, family_id=command.family_id)
            self._uow.commit()
        return Ok(milestone)


@dataclass(frozen=True, slots=True)
class GrandparentPrompt:
    child_id: ChildId
    child_name: str
    milestone_age_years: int
    prompt_text: str
    birthday: date


@dataclass(frozen=True, slots=True)
class RespondGrandparentPromptCommand:
    family_id: FamilyId
    grandparent_id: MemberId
    child_id: ChildId
    milestone_age_years: int
    audio_media_id: str | None = None
    text: str | None = None


class GrandparentPromptUseCase:
    """PRD 27 - Grandparent zero-install prompt 30 days before child turns N."""

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
        self._skipped_prompts: set[tuple[str, str, int]] = set()

    def check_eligible_prompt(
        self, family_id: FamilyId, grandparent_id: MemberId, child_id: ChildId
    ) -> Result[GrandparentPrompt | None, DomainError]:
        family_result = self._families.get(family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()

        member_result = family.member(grandparent_id)
        if member_result.is_err():
            return Err(member_result.unwrap_err())
        member = member_result.unwrap()
        if member.role != MemberRole.GRANDPARENT:
            return Err(
                DomainError(
                    ErrorCode.PERMISSION_DENIED,
                    f"member {grandparent_id} is not a grandparent",
                )
            )

        child_result = family.child(child_id)
        if child_result.is_err():
            return Err(child_result.unwrap_err())
        child = child_result.unwrap()

        today = self._clock.today()
        # Calculate next birthday
        next_bday_year = today.year
        if (today.month, today.day) > (child.date_of_birth.month, child.date_of_birth.day):
            next_bday_year += 1
        next_bday = date(next_bday_year, child.date_of_birth.month, child.date_of_birth.day)

        days_until_bday = (next_bday - today).days
        milestone_age = next_bday_year - child.date_of_birth.year

        # Check if permanently skipped
        if (str(grandparent_id), str(child_id), milestone_age) in self._skipped_prompts:
            return Ok(None)

        # 30 days before child turns N
        if 0 <= days_until_bday <= 30:
            prompt_text = f"What was his father like at {milestone_age}?"
            return Ok(
                GrandparentPrompt(
                    child_id=child_id,
                    child_name=child.display_name,
                    milestone_age_years=milestone_age,
                    prompt_text=prompt_text,
                    birthday=next_bday,
                )
            )
        return Ok(None)

    def skip_forever(
        self,
        family_id: FamilyId,  # noqa: ARG002 - part of the call shape; the key below is
        # already family-unique because a member id belongs to exactly one family.
        grandparent_id: MemberId,
        child_id: ChildId,
        milestone_age_years: int,
    ) -> Result[None, DomainError]:
        self._skipped_prompts.add((str(grandparent_id), str(child_id), milestone_age_years))
        return Ok(None)

    def record_response(
        self, command: RespondGrandparentPromptCommand
    ) -> Result[LittleThing, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()

        member_result = family.member(command.grandparent_id)
        if member_result.is_err():
            return Err(member_result.unwrap_err())

        # Tag filed against two ages at once: child age N and parent age N
        content_text = command.text
        dual_age_note = (
            f"[Ages: Child at {command.milestone_age_years}, "
            f"Parent at {command.milestone_age_years}]"
        )
        content_text = f"{dual_age_note} {content_text}" if content_text else dual_age_note

        created = LittleThing.capture(
            little_thing_id=LittleThingId(self._ids.new_id()),
            family_id=command.family_id,
            author_id=command.grandparent_id,
            subject_child_id=command.child_id,
            text=content_text,
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

        # Skippable/answered forever; never re-asked for this age
        self._skipped_prompts.add(
            (str(command.grandparent_id), str(command.child_id), command.milestone_age_years)
        )
        return Ok(thing)
