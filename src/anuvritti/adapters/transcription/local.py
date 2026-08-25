"""Transcription that cannot phone home (TASK-603; PRD 39, 44).

PRD 44 lists "no public-model training by default" among the core privacy principles. The
word doing the work is *default*, and a default is a setting - something a future release,
a hurried deployment or a well-meaning environment variable can flip. This module exists
to make that promise structural instead, so that turning it off is a code change that
shows up in a diff and fails a test.

There are exactly two ways audio could leave a family's box: this adapter could open a
socket, or it could hand the bytes to something that does. So:

* This package imports **no network module** - not `socket`, not `ssl`, not `http.client`,
  not `urllib.request`, not any vendor SDK. `tests/constitution/test_no_public_model.py`
  walks the transitive import graph of every module under `anuvritti.adapters` and fails
  the build if one appears. A static walk, not a runtime check, because a runtime check
  only fires on the request that already sent the audio.
* The `SpeechModel` port takes **bytes and returns words**. It is not given a media id, a
  store, a session, a config or a URL. An adapter behind it can still do something foolish
  with the bytes, but it cannot be handed the address of anywhere to send them, and the
  narrowness of that signature is the point.

The shipping default is `SilentTranscriber`, which returns nothing at all. That is not a
placeholder. A recording with no transcript is complete; a recording with a wrong
transcript is a piece of family history with a plausible lie attached to it, and the lie
is the part that gets read in ten years. When a family installs a local model, they get an
index. Until then they have the thing that mattered, which was always the recording.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from anuvritti.application.ports import MediaStore
from anuvritti.domain.media import MediaKind
from anuvritti.domain.values import Confidence
from anuvritti.domain.voice import Transcript
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import MediaId
from anuvritti.shared.result import Err, Ok, Result

#: The same ceiling the Intent Engine uses. An engine may be confident; it may not be
#: certain, because certainty belongs to the person who was in the room (PRD 8.7).
MAX_CONFIDENCE: Final = 0.85


@dataclass(frozen=True, slots=True)
class Heard:
    """What a model thinks it heard, and how sure it is."""

    text: str
    confidence: float


@runtime_checkable
class SpeechModel(Protocol):
    """A local model. Bytes in, words out, and deliberately nothing else in the signature.

    Returning `None` means "I could not make anything of that", which is an ordinary
    outcome for a four-second clip recorded next to a running tap and must never be an
    error - the recording is kept either way.
    """

    @property
    def name(self) -> str:
        """What to write in the provenance. `whisper.cpp-tiny`, not `ai`."""
        ...

    def listen(self, audio: bytes, *, mime_type: str) -> Heard | None: ...


class SilentTranscriber:
    """The default. Keeps every recording and indexes none of them.

    This is the honest V1 answer for a product that runs on a box in someone's house: no
    cloud call, and no pretence that a general-purpose model is installed on it.
    """

    __slots__ = ()

    def transcribe(self, media_id: MediaId) -> Result[Transcript | None, DomainError]:  # noqa: ARG002 - the port's shape; there is nothing to look at
        return Ok(None)


class LocalTranscriber:
    """Runs a locally-installed model over locally-stored bytes.

    Composed of a `MediaStore` and a `SpeechModel` and nothing else. It has no client, no
    base URL and no credentials, because there is nowhere for it to send anything.
    """

    __slots__ = ("_clock", "_media", "_model")

    def __init__(self, *, media: MediaStore, model: SpeechModel | None, clock: Clock) -> None:
        self._media = media
        self._model = model
        self._clock = clock

    def transcribe(self, media_id: MediaId) -> Result[Transcript | None, DomainError]:
        described = self._media.describe(media_id)
        if described.is_err():
            return Err(described.unwrap_err())

        media = described.unwrap()
        if media.kind is not MediaKind.AUDIO:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_KIND_UNSUPPORTED,
                    "only audio can be transcribed",
                    {"kind": media.kind.value},
                )
            )

        if self._model is None:
            # No model installed. Not a failure - the recording still stands on its own.
            return Ok(None)

        content = self._media.get(media_id)
        if content.is_err():  # pragma: no cover - describe already proved it is there
            return Err(content.unwrap_err())

        heard = self._model.listen(content.unwrap(), mime_type=media.mime_type)
        if heard is None or not heard.text.strip():
            return Ok(None)

        # Clamped rather than validated. A model reporting 1.0 is a model that has stopped
        # being able to be wrong, and the right response is to write down a lower number,
        # not to throw away what it heard.
        written = Transcript.machine(
            heard.text,
            confidence=Confidence(min(max(heard.confidence, 0.0), MAX_CONFIDENCE)),
            engine=self._model.name,
            at=self._clock.now(),
        )
        if written.is_err():
            return Err(written.unwrap_err())
        return Ok(written.unwrap())
