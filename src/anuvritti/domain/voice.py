"""Voice notes (PRD 12, 17, 21, 24).

One rule shapes every line of this module:

    **The recording is the artifact. The transcript is only an index.**

That sounds like a UI preference. It is actually a data rule, and it has to be held here
or it will not be held at all, because every downstream pressure runs the other way. Text
is searchable, diffable, cheap to render and easy to summarise; a 4.2-second m4a of a man
laughing halfway through a sentence is none of those things. Every system that has ever
stored both has ended up treating the text as the record and the audio as an attachment.

So the aggregate is *the recording*. Its identity is the `MediaId` of the audio, not a
surrogate key - a `VoiceNote` without audio is not a degraded voice note, it is not a
voice note, and there is no constructor that produces one. A transcript is a nullable
field hanging off it, carrying its own provenance (PRD 8.7), and attaching one is a pure
function that cannot reach the audio.

The second rule is PRD 24: nothing is rejected for being unpolished. There is no minimum
duration in this file and `tests/constitution/test_preserve_imperfection.py` exists to
keep it that way. A half-second clip of someone starting to say something and giving up
is a real thing that happened, and in ten years it may be the more interesting half.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from anuvritti.domain.events import DomainEvent, VoiceNoteIndexed, VoiceNoteKept
from anuvritti.domain.values import AttributionSource, Confidence
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId, MemberId
from anuvritti.shared.result import Err, Ok, Result

#: Four hours. Not a judgement about length - a bound on what ffprobe may report before a
#: malformed container poisons every duration sum in the film.
MAX_DURATION_SECONDS: Final = 4 * 60 * 60.0

#: What an engine is called when there is no engine. A transcript never has an unnamed
#: author: "we do not know who said this" is not an acceptable state for family history.
NO_ENGINE: Final = "none"

#: The engine name a parent's own correction carries.
BY_HAND: Final = "hand"

_TRANSCRIPT_MAX: Final = 20_000


@dataclass(frozen=True, slots=True)
class Transcript:
    """Words that stand in for a recording in a search box, and nowhere else.

    `source` is the same three-way distinction PRD 8.7 draws everywhere else in the
    product: recorded truth, human interpretation, machine interpretation. A transcript is
    never recorded truth - the recording is - so the only two values it can carry are AI
    and HUMAN, and the constructors are the only way to make one.
    """

    text: str
    source: AttributionSource
    confidence: Confidence
    engine: str
    made_at: datetime

    @classmethod
    def machine(
        cls, text: str, *, confidence: Confidence, engine: str, at: datetime
    ) -> Result[Transcript, DomainError]:
        """A machine's best reading. Always a guess, however good it is."""
        cleaned = _clean(text)
        if cleaned is None:
            return _blank("a transcript")
        if not engine.strip():
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED, "a machine transcript must name its engine"
                )
            )
        if confidence >= Confidence.CERTAIN:
            # Certainty is reserved for what a person actually said (PRD 8.7). An engine
            # that reports 1.0 is an engine that has stopped being able to be wrong.
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "a machine transcript may not claim certainty",
                    {"engine": engine},
                )
            )
        return Ok(cls(cleaned, AttributionSource.AI, confidence, engine.strip(), at))

    @classmethod
    def by_hand(cls, text: str, *, at: datetime) -> Result[Transcript, DomainError]:
        """A person typed what was said. That is the end of the discussion."""
        cleaned = _clean(text)
        if cleaned is None:
            return _blank("a transcript")
        return Ok(cls(cleaned, AttributionSource.HUMAN, Confidence.CERTAIN, BY_HAND, at))

    @property
    def is_machine_made(self) -> bool:
        return self.source is AttributionSource.AI

    @property
    def is_uncertain(self) -> bool:
        """Show it as a reading, not as a quotation."""
        return self.confidence.is_low

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source.value,
            "confidence": self.confidence.value,
            "engine": self.engine,
            "made_at": self.made_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class VoiceNote:
    """A recording that was kept, and whatever is known about what is in it.

    Identity is `media_id` on purpose. There is no `VoiceNoteId`, because a second
    identifier would let a voice note outlive its audio - a row saying "there used to be a
    recording here, and here is roughly what it said" is precisely the artefact this
    module exists to make impossible to create.
    """

    media_id: MediaId
    family_id: FamilyId
    author_id: MemberId
    duration_seconds: float
    recorded_at: datetime
    transcript: Transcript | None = None
    pending_events: tuple[DomainEvent, ...] = ()

    @classmethod
    def kept(
        cls,
        *,
        media_id: MediaId,
        family_id: FamilyId,
        author_id: MemberId,
        duration_seconds: float,
        at: datetime,
    ) -> Result[VoiceNote, DomainError]:
        """Keep it. PRD 24 - there is no bar to clear.

        The only rejected durations are the two that are not durations: a negative number
        and one longer than a working day. Neither describes a short recording; both
        describe a client that has lost track of what it is sending.
        """
        if duration_seconds != duration_seconds or duration_seconds in (
            float("inf"),
            float("-inf"),
        ):  # NaN compares unequal to itself; both are arithmetic accidents, not lengths
            return Err(
                DomainError(ErrorCode.VALIDATION_FAILED, "a recording needs a real duration")
            )
        if duration_seconds < 0:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "a recording cannot be shorter than no time at all",
                    {"duration_seconds": duration_seconds},
                )
            )
        if duration_seconds > MAX_DURATION_SECONDS:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "that is longer than this endpoint will accept in one recording",
                    {"max_duration_seconds": MAX_DURATION_SECONDS},
                )
            )
        return Ok(
            cls(
                media_id=media_id,
                family_id=family_id,
                author_id=author_id,
                duration_seconds=float(duration_seconds),
                recorded_at=at,
                transcript=None,
                pending_events=(VoiceNoteKept(aggregate_id=str(media_id), occurred_at=at),),
            )
        )

    def indexed_by(self, transcript: Transcript) -> VoiceNote:
        """Attach a machine reading - unless a person has already said what was said.

        The same rule `Attributed.reinferred` holds for every other inferred field: a
        human correction is permanent and a later run of a better model does not get to
        quietly undo it (PRD 13).
        """
        if self.transcript is not None and not self.transcript.is_machine_made:
            return self
        if not transcript.is_machine_made:  # pragma: no cover - `corrected_to` is the door
            return self
        return self._evolve(
            transcript=transcript,
            event=VoiceNoteIndexed(
                aggregate_id=str(self.media_id),
                occurred_at=transcript.made_at,
                engine=transcript.engine,
                source=transcript.source.value,
            ),
        )

    def corrected_to(self, text: str, *, at: datetime) -> Result[VoiceNote, DomainError]:
        """A parent fixes what the machine misheard. Permanent, and never trims the audio."""
        written = Transcript.by_hand(text, at=at)
        if written.is_err():
            return Err(written.unwrap_err())
        corrected = written.unwrap()
        return Ok(
            self._evolve(
                transcript=corrected,
                event=VoiceNoteIndexed(
                    aggregate_id=str(self.media_id),
                    occurred_at=at,
                    engine=corrected.engine,
                    source=corrected.source.value,
                ),
            )
        )

    @property
    def is_indexed(self) -> bool:
        return self.transcript is not None

    @property
    def searchable_text(self) -> str | None:
        """What a search box may match on. `None` is a fine answer.

        A recording with no transcript is not a broken record and must not be hidden from
        the vault - it is simply one the search box cannot help with yet.
        """
        return self.transcript.text if self.transcript else None

    def with_events_cleared(self) -> VoiceNote:
        return replace(self, pending_events=())

    def _evolve(self, *, event: DomainEvent | None = None, **changes: Any) -> VoiceNote:
        events = (*self.pending_events, event) if event is not None else self.pending_events
        return replace(self, pending_events=events, **changes)


def _clean(text: str) -> str | None:
    stripped = text.strip()
    return stripped[:_TRANSCRIPT_MAX] if stripped else None


def _blank(what: str) -> Err[DomainError]:
    return Err(DomainError(ErrorCode.VALIDATION_FAILED, f"{what} cannot be blank"))
