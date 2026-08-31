"""The film - a year of a life, assembled from things that actually happened (PRD 34).

PRD 34 promises a child a film at four and again at eighteen. The temptation in that
promise is to treat the film as *output*: pour the archive into a template, add music, ship
an mp4. This module refuses that shape in three places, and each refusal is a type rather
than a convention.

**A scene must cite.** `FilmScene.cites` holds the identifiers a parent can follow back to
the Spark, Moment, recording or photo the scene claims to be about. Nothing here interprets
a citation - that is TASK-706's job - but a scene physically cannot be built without a place
to put one, which is what stops a beautiful invented memory from ever being cheap to make.

**A voice has a measured length.** `SceneVoice.seconds` is how long the audio *is*, not how
long the words *ought to take*. There is no words-per-minute anywhere in this module and no
field to put one in. A film that guesses will eventually cut a parent off mid-sentence, and
the person it cuts off will be the one child who most needed to hear the end.

**Nothing here describes a picture.** No codec, no resolution beyond a frame size, no output
path, no renderer. The film is planned in the domain and drawn somewhere else entirely - see
`FilmCompiler` in the application ports for why that separation is not merely tidy.

**A film travels with the files it names, and with nothing else.** `FilmDraft` holds a spec
and a `MediaBundle`, and refuses to exist unless the two agree exactly: no scene may name a
file the bundle does not carry, and the bundle may not carry a file no scene names. The first
half stops a film from being drawn with a hole in it; the second half matters more, because a
bundle is what *leaves the house* for the machine that draws the film, and a spare recording
in it is a recording of a child that travelled for no reason.

**A citation is checked, not trusted.** `FilmScene` guarantees that a citation was *written*;
`Provenance` is the record of someone having gone and *looked*. A `FilmPackage` cannot be
constructed around a ledger that is incomplete or that found anything missing or altered, so
"the film cites only real things" stops being a property of whichever code built the spec and
becomes a property of every film that exists. The ledger ships as `provenance.json` beside the
film, because the claim a child is owed in fifteen years is not "trust us" - it is a list of
identifiers they can go and look up themselves.

**A machine gets four sentences, and it never says them over a memory.** `ConnectiveLine` is
the entire vocabulary a synthesiser is permitted: fixed in this file, containing no name, no
date and nowhere to put one. `SceneVoice` will not hold a synthetic voice that says anything
else, and `FilmScene` will not hold one over a scene that cites - so "synthesis is only ever
neutral connective tissue" is checked where the scene is built, not left to whoever writes
the next composer. Every synthetic voice is still a real file with a measured length, for the
same reason a recorded one is: there is no words-per-minute anywhere in this module, and a
machine reading a sentence quickly is not thirty seconds of film.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from anuvritti.domain.media import MediaKind
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MediaId
from anuvritti.shared.result import Err, Ok, Result

#: Silence before the first word of a scene. Long enough that a picture has arrived before a
#: voice starts, short enough that it never reads as a gap. A taste decision, which is why it
#: lives in the product and not in the compiler.
DEFAULT_LEAD_IN_SECONDS = 0.35

#: Silence after the last word. Longer than the lead-in on purpose: a sentence needs somewhere
#: to land, and cutting on the final consonant is the single most common way home video feels
#: rushed.
DEFAULT_TAIL_SECONDS = 0.55

#: How long a whole film is aiming for, and how far past that is still fine. A year is allowed
#: to run long; see `CompiledFilm.notes`.
DEFAULT_TARGET_SECONDS = 180.0

#: The last line of every film this product makes. It lives here rather than with the composer
#: because it is also the one thing a machine is allowed to say about the film as a whole, and
#: a claim that strong should sit next to the types that make it true.
CLOSING_LINE = "Everything here happened. Nothing here was invented."
DEFAULT_TOLERANCE_SECONDS = 5.0

_FRAME_WIDTH = 1920
_FRAME_HEIGHT = 1080
_FPS = 30


class SceneKind(StrEnum):
    """What a scene is doing, not what it looks like.

    The renderer maps these to layouts; the compiler only uses them to label the timeline so
    a person reading `provenance.json` in fifteen years can tell a title card from a memory.
    """

    OPENING = "OPENING"
    SPARK = "SPARK"
    MOMENT = "MOMENT"
    VOICE = "VOICE"
    LITTLE_THING = "LITTLE_THING"
    PROMISE_KEPT = "PROMISE_KEPT"
    CLOSING = "CLOSING"

    @property
    def is_evidence(self) -> bool:
        """Whether a scene of this kind is claiming that something happened.

        A title card claims nothing and cites nothing. Every other kind is an assertion about
        a real child's real life, and an assertion with no citation is precisely the shape an
        invented memory arrives in - plausible, well-made, and about nothing. `FilmScene`
        turns that from a review comment into a construction error.
        """
        return self not in (SceneKind.OPENING, SceneKind.CLOSING)


class ConnectiveLine(StrEnum):
    """Every sentence a machine is allowed to say out loud in an Anuvritti film.

    Not a default set, not a starting point - the whole vocabulary. Each line is a fact about
    the *film* rather than about the child: it introduces, it separates, it signs off. None of
    them contains a name, a date, an age, an adjective or a format placeholder, which is what
    makes "synthesis is neutral" checkable rather than a matter of taste.

    The reason it is an enum and not a string is that the `Narrator` port takes one of these
    and nothing else. There is no parameter anywhere in this codebase through which a sentence
    about somebody's child could reach a synthesiser, and a closed type is how that stays true
    after the person who wrote it has moved on.
    """

    OPENING = "OPENING"
    IN_THEIR_OWN_VOICE = "IN_THEIR_OWN_VOICE"
    A_LITTLE_LATER = "A_LITTLE_LATER"
    CLOSING = "CLOSING"

    @property
    def words(self) -> str:
        """What is actually spoken. Fixed text - there is no interpolation and no argument."""
        return _CONNECTIVE_WORDS[self]


_CONNECTIVE_WORDS: dict[ConnectiveLine, str] = {
    ConnectiveLine.OPENING: "These are things that happened.",
    ConnectiveLine.IN_THEIR_OWN_VOICE: "In their own voice.",
    ConnectiveLine.A_LITTLE_LATER: "A little later.",
    ConnectiveLine.CLOSING: CLOSING_LINE,
}

#: How a synthetic line is labelled wherever it is written down or drawn. It is deliberately
#: plain: a parent reading a caption should not need to know what a synthesiser is to
#: understand that the voice they are hearing is not a person.
MACHINE_MARK = "read by a machine"


class CitationKind(StrEnum):
    """The kinds of thing a scene can claim to be evidence of."""

    SPARK = "SPARK"
    MOMENT = "MOMENT"
    MEDIA = "MEDIA"
    VOICE_NOTE = "VOICE_NOTE"
    LITTLE_THING = "LITTLE_THING"
    SOUND_BED = "SOUND_BED"


class NarrationOrigin(StrEnum):
    """Who is speaking - and `SYNTHETIC` is a confession, not a feature (PRD 8.7, 47).

    `RECORDED` is a real person who really said this. `SYNTHETIC` is a machine reading words
    nobody spoke aloud, permitted only for neutral connective tissue and marked wherever it
    appears. `SILENT` is a scene that holds without a voice, which is a legitimate and often
    better answer than inventing one.
    """

    RECORDED = "RECORDED"
    SYNTHETIC = "SYNTHETIC"
    SILENT = "SILENT"


@dataclass(frozen=True, slots=True)
class Citation:
    """One identifier a reviewer can follow back to something that exists."""

    kind: CitationKind
    id: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("a citation with no id cites nothing")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "id": self.id}


@dataclass(frozen=True, slots=True)
class SceneVoice:
    """What is heard over a scene, and how long it actually lasts.

    `seconds` is a measurement. For `RECORDED` it is the length of the file a parent made;
    for `SYNTHETIC` it is the length of the file a synthesiser produced, probed after the
    fact. It is never derived from the text, which is why `text` and `seconds` can disagree
    wildly - a slow, careful sentence and a fast one have the same word count and are not
    the same scene.
    """

    origin: NarrationOrigin
    seconds: float
    text: str = ""
    media_id: MediaId | None = None
    line: ConnectiveLine | None = None

    def __post_init__(self) -> None:
        if self.seconds < 0:
            raise ValueError(f"a voice cannot last {self.seconds} seconds")
        if self.origin is NarrationOrigin.RECORDED and self.media_id is None:
            raise ValueError(
                "a recorded voice is a file; without a media id there is nothing to play"
            )
        if self.origin is NarrationOrigin.SYNTHETIC:
            self._check_synthetic()
        elif self.line is not None:
            raise ValueError("only a machine reads from the connective lines")
        if self.origin is NarrationOrigin.SILENT and (self.text.strip() or self.media_id):
            raise ValueError("a silent scene may not carry words or audio")

    def _check_synthetic(self) -> None:
        """The three things that separate connective tissue from a machine telling a story.

        A line from the fixed catalogue, spoken words that are exactly that line, and a real
        file behind it. The third is the one that looks like paperwork and is not: without a
        file there is no measurement, and without a measurement the only remaining way to know
        how long the voice lasts is to count the words and divide - which this module refuses
        to do for a parent and will not start doing for a synthesiser either.
        """
        if self.line is None:
            raise ValueError(
                "a machine may only read one of the connective lines, and this is not one of them"
            )
        if self.text != self.line.words:
            raise ValueError(
                f"a synthetic voice says {self.line.value} exactly, not {self.text[:40]!r}"
            )
        if self.media_id is None:
            raise ValueError(
                "a synthetic voice is a file too; its length is measured from the file, "
                "because the alternative is estimating it from the words"
            )

    @classmethod
    def recorded(cls, *, media_id: MediaId, seconds: float, text: str = "") -> SceneVoice:
        """A parent's own recording. `text` is its transcript, used only for captions."""
        return cls(NarrationOrigin.RECORDED, seconds, text=text, media_id=media_id)

    @classmethod
    def synthetic(cls, *, line: ConnectiveLine, media_id: MediaId, seconds: float) -> SceneVoice:
        """One of the four lines, read aloud into a file somebody then measured.

        There is no `text` parameter. That is the whole point of this constructor.
        """
        return cls(
            NarrationOrigin.SYNTHETIC, seconds, text=line.words, media_id=media_id, line=line
        )

    @classmethod
    def silent(cls, seconds: float) -> SceneVoice:
        return cls(NarrationOrigin.SILENT, seconds)

    @property
    def is_real_voice(self) -> bool:
        return self.origin is NarrationOrigin.RECORDED

    @property
    def is_synthetic(self) -> bool:
        return self.origin is NarrationOrigin.SYNTHETIC

    @property
    def caption(self) -> str:
        """The words as they should be *shown*, which is not always the words as spoken.

        A caption is read as a quotation, so a machine's sentence carries its mark into the
        picture. This property is the single place that mark is applied: the compiler puts
        this on the timeline, the timeline is what captions are cut from, and a renderer that
        wants the unmarked words has to go and ask for `text` on purpose.
        """
        if self.is_synthetic and self.text:
            return f"[{MACHINE_MARK}] {self.text}"
        return self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin.value,
            "seconds": round(self.seconds, 3),
            "text": self.text,
            "media_id": str(self.media_id) if self.media_id else None,
            "line": self.line.value if self.line else None,
            "read_by_a_machine": self.is_synthetic,
        }


@dataclass(frozen=True, slots=True)
class FilmScene:
    """One held picture with one voice over it.

    `max_seconds` is a cap a parent can set, and the compiler treats it as a refusal rather
    than a trim: a recording longer than its cap fails the compile with the scene named,
    instead of being quietly cut off. Trimming is how a sentence disappears from a finished
    film with nothing anywhere saying that it did.
    """

    id: str
    kind: SceneKind
    heading: str
    voice: SceneVoice
    body: str = ""
    cites: tuple[Citation, ...] = ()
    lead_in_seconds: float = DEFAULT_LEAD_IN_SECONDS
    tail_seconds: float = DEFAULT_TAIL_SECONDS
    min_seconds: float = 0.0
    max_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("a scene needs an id")
        if self.kind.is_evidence and not self.cites:
            raise ValueError(
                f"{self.id}: a {self.kind.value} scene that cites nothing is a story, not a memory"
            )
        if self.kind.is_evidence and self.voice.is_synthetic:
            raise ValueError(
                f"{self.id}: a machine may introduce a memory, but it may not narrate one"
            )
        if self.lead_in_seconds < 0 or self.tail_seconds < 0:
            raise ValueError("padding is silence, and there is no negative silence")
        if self.min_seconds < 0:
            raise ValueError(f"{self.id}: min_seconds cannot be negative")
        if self.max_seconds is not None and self.max_seconds < self.min_seconds:
            raise ValueError(f"{self.id}: max_seconds is below min_seconds")

    @property
    def cited_ids(self) -> frozenset[str]:
        return frozenset(citation.id for citation in self.cites)

    @property
    def media_ids(self) -> frozenset[str]:
        """Every real file this scene needs: the audio it plays, and the media it shows."""
        named = {str(self.voice.media_id)} if self.voice.media_id else set()
        return frozenset(
            named
            | {c.id for c in self.cites if c.kind in (CitationKind.MEDIA, CitationKind.SOUND_BED)}
        )


@dataclass(frozen=True, slots=True)
class FilmSpec:
    """The whole film, planned. Everything needed to compile it and nothing about drawing it."""

    id: str
    family_id: FamilyId
    title: str
    scenes: tuple[FilmScene, ...]
    spec_version: str = "1.0"
    child_id: ChildId | None = None
    fps: int = _FPS
    width: int = _FRAME_WIDTH
    height: int = _FRAME_HEIGHT
    target_seconds: float = DEFAULT_TARGET_SECONDS
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS

    @property
    def scene_ids(self) -> tuple[str, ...]:
        return tuple(scene.id for scene in self.scenes)

    @property
    def media_ids(self) -> frozenset[str]:
        """Every file the whole film names. What a `MediaBundle` must carry, exactly."""
        return frozenset(media_id for scene in self.scenes for media_id in scene.media_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "id": self.id,
            "family_id": str(self.family_id),
            "title": self.title,
            "scenes": [
                {
                    "id": scene.id,
                    "kind": scene.kind.value,
                    "heading": scene.heading,
                    "body": scene.body,
                    "voice": scene.voice.to_dict(),
                    "cites": [c.to_dict() for c in scene.cites],
                    "lead_in_seconds": scene.lead_in_seconds,
                    "tail_seconds": scene.tail_seconds,
                    "min_seconds": scene.min_seconds,
                    "max_seconds": scene.max_seconds,
                }
                for scene in self.scenes
            ],
            "child_id": str(self.child_id) if self.child_id else None,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "target_seconds": self.target_seconds,
            "tolerance_seconds": self.tolerance_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Result[FilmSpec, DomainError]:
        version = data.get("spec_version", "1.0")
        try:
            major = int(str(version).split(".")[0])
        except Exception:
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    f"invalid filmspec version string '{version}'",
                    {"version": str(version)},
                )
            )

        if major > 1:
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    f"unsupported future FilmSpec version '{version}' - requires newer compiler",
                    {"spec_version": str(version)},
                )
            )

        try:
            scenes = []
            for s in data.get("scenes", []):
                kind = SceneKind(s["kind"])
                v_data = s.get("voice", {})
                origin = NarrationOrigin(v_data.get("origin", "SILENT"))
                sec = float(v_data.get("seconds", 0.0))
                text = v_data.get("text", "")
                mid = MediaId(v_data["media_id"]) if v_data.get("media_id") else None
                line = ConnectiveLine(v_data["line"]) if v_data.get("line") else None

                if origin is NarrationOrigin.RECORDED and mid:
                    voice = SceneVoice.recorded(media_id=mid, seconds=sec, text=text)
                elif origin is NarrationOrigin.SYNTHETIC and line and mid:
                    voice = SceneVoice.synthetic(line=line, media_id=mid, seconds=sec)
                else:
                    voice = SceneVoice.silent(seconds=sec)

                cites = tuple(
                    Citation(
                        kind=CitationKind(c["kind"]),
                        id=c["id"],
                    )
                    for c in s.get("cites", [])
                )

                scenes.append(
                    FilmScene(
                        id=s["id"],
                        kind=kind,
                        heading=s.get("heading", ""),
                        voice=voice,
                        body=s.get("body", ""),
                        cites=cites,
                        lead_in_seconds=float(s.get("lead_in_seconds", DEFAULT_LEAD_IN_SECONDS)),
                        tail_seconds=float(s.get("tail_seconds", DEFAULT_TAIL_SECONDS)),
                        min_seconds=float(s.get("min_seconds", 0.0)),
                        max_seconds=(
                            float(s["max_seconds"]) if s.get("max_seconds") is not None else None
                        ),
                    )
                )

            spec = cls(
                id=data["id"],
                family_id=FamilyId(data["family_id"]),
                title=data["title"],
                scenes=tuple(scenes),
                spec_version=str(version),
                child_id=ChildId(data["child_id"]) if data.get("child_id") else None,
                fps=int(data.get("fps", _FPS)),
                width=int(data.get("width", _FRAME_WIDTH)),
                height=int(data.get("height", _FRAME_HEIGHT)),
                target_seconds=float(data.get("target_seconds", DEFAULT_TARGET_SECONDS)),
                tolerance_seconds=float(data.get("tolerance_seconds", DEFAULT_TOLERANCE_SECONDS)),
            )
            return Ok(spec)
        except Exception as exc:
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    f"failed to parse FilmSpec: {exc}",
                    {"details": str(exc)},
                )
            )


@dataclass(frozen=True, slots=True)
class Cue:
    """A caption, in film time. Comes from the narration; there is nowhere to author one."""

    start_seconds: float
    end_seconds: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class AudioDescriptionCue:
    """An audio description cue for accessibility (PRD 27, PRD 56)."""

    start_seconds: float
    end_seconds: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class CompiledScene:
    """A scene with its place in the film settled.

    The invariant in `__post_init__` is the one that matters. A compiled scene whose audio
    outlasts its picture is a scene that will be cut off, and this type will not hold one -
    so the failure surfaces where it can still be fixed rather than in the finished film.
    """

    id: str
    kind: SceneKind
    start_seconds: float
    visual_seconds: float
    voice: SceneVoice
    cites: tuple[Citation, ...] = ()

    def __post_init__(self) -> None:
        if self.voice.seconds > self.visual_seconds + 1e-6:
            raise ValueError(
                f"{self.id}: {self.voice.seconds:.3f}s of voice in a "
                f"{self.visual_seconds:.3f}s scene - it would be cut off"
            )

    @property
    def audio_seconds(self) -> float:
        return self.voice.seconds

    @property
    def padding_seconds(self) -> float:
        """Silence around the voice. Positive by construction."""
        return self.visual_seconds - self.voice.seconds

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.visual_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "start_seconds": round(self.start_seconds, 3),
            "visual_seconds": round(self.visual_seconds, 3),
            "voice": self.voice.to_dict(),
            "cites": [citation.to_dict() for citation in self.cites],
        }


@dataclass(frozen=True, slots=True)
class CompiledFilm:
    """A film that adds up: every scene placed, every caption timed, nothing drawn yet.

    `timeline` and `timing` are the compiler's own reports, carried through opaquely. The
    domain does not read them; they travel with the film so that whatever draws it is working
    from the same arithmetic that was checked here, rather than re-deriving durations and
    quietly disagreeing.
    """

    spec_id: str
    title: str
    scenes: tuple[CompiledScene, ...]
    cues: tuple[Cue, ...] = ()
    audio_descriptions: tuple[AudioDescriptionCue, ...] = ()
    timeline: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def duration_seconds(self) -> float:
        return sum(scene.visual_seconds for scene in self.scenes)

    @property
    def recorded_seconds(self) -> float:
        return sum(s.audio_seconds for s in self.scenes if s.voice.is_real_voice)

    @property
    def synthetic_seconds(self) -> float:
        return sum(
            s.audio_seconds for s in self.scenes if s.voice.origin is NarrationOrigin.SYNTHETIC
        )

    @property
    def real_voice_share(self) -> float:
        """How much of the spoken film is a person. A film with no voice at all scores 1.0.

        Not a vanity metric. PRD 47 makes this the number a parent is owed before they show
        the film to their child: if it has drifted, they should find out from the app rather
        than from a sentence their father never said.
        """
        spoken = self.recorded_seconds + self.synthetic_seconds
        return 1.0 if spoken == 0 else self.recorded_seconds / spoken

    @property
    def synthetic_scene_ids(self) -> tuple[str, ...]:
        """Which scenes a machine speaks over. Empty for almost every film this makes."""
        return tuple(scene.id for scene in self.scenes if scene.voice.is_synthetic)

    @property
    def narration(self) -> dict[str, Any]:
        """The whole voice accounting in one place, so it travels with the film.

        This block is written into `film.json` beside the ledger of citations, and it answers
        the question a parent has before they show a film to their child: whose voice is this.
        Seconds rather than scene counts, because a film can be nine-tenths real by scene and
        half a machine by the clock.
        """
        return {
            "recorded_seconds": round(self.recorded_seconds, 3),
            "synthetic_seconds": round(self.synthetic_seconds, 3),
            "real_voice_share": round(self.real_voice_share, 4),
            "synthetic_scenes": list(self.synthetic_scene_ids),
            "synthetic_lines": sorted(
                {s.voice.line.value for s in self.scenes if s.voice.line is not None}
            ),
        }

    @property
    def citations(self) -> tuple[Citation, ...]:
        return tuple(citation for scene in self.scenes for citation in scene.cites)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "title": self.title,
            "duration_seconds": round(self.duration_seconds, 3),
            "scene_count": len(self.scenes),
            "real_voice_share": round(self.real_voice_share, 4),
            "narration": self.narration,
            "notes": list(self.notes),
            "scenes": [scene.to_dict() for scene in self.scenes],
            "cues": [cue.to_dict() for cue in self.cues],
            "audio_descriptions": [ad.to_dict() for ad in self.audio_descriptions],
            # The renderer consumes the arithmetic the compiler checked. Reconstructing
            # it from rounded summaries at the far end is how audio and picture drift.
            "timeline": self.timeline,
            "timing": self.timing,
        }


@dataclass(frozen=True, slots=True)
class BundledMedia:
    """One real file the film draws from, described without ever holding its bytes.

    `content_hash` is the reason this type exists rather than a bare list of ids. The machine
    that draws the film is not the machine that holds the archive, so the file arrives having
    travelled, and "is this the recording the compiler measured?" has to be answerable at the
    far end by something other than trust.
    """

    id: MediaId
    kind: MediaKind
    mime_type: str
    byte_size: int
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": self.kind.value,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class MediaBundle:
    """The files a film needs, listed once each."""

    items: tuple[BundledMedia, ...] = ()

    def __post_init__(self) -> None:
        listed = [str(item.id) for item in self.items]
        if len(set(listed)) != len(listed):
            raise ValueError("a bundle lists each file once")

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(str(item.id) for item in self.items)

    @property
    def byte_size(self) -> int:
        """What the family is about to copy off their own machine."""
        return sum(item.byte_size for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.items),
            "byte_size": self.byte_size,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class FilmDraft:
    """A film and exactly the real files it draws from (PRD 15, 23, 34).

    The two halves of the invariant are not the same kind of rule.

    Nothing missing is about correctness: a scene naming a recording that is not in the bundle
    is a film that draws with a hole in it, and the hole would be discovered by a renderer on
    another machine, at which point the honest options are to fail or to invent something.

    Nothing spare is about privacy, and it is the half worth defending in review. A bundle is
    what leaves the family's box - the archive stays home, the bundle travels. Every file in it
    is a photograph or a recording of a child, and one that no scene names is one that made
    that trip for no reason at all.
    """

    spec: FilmSpec
    bundle: MediaBundle

    def __post_init__(self) -> None:
        named = self.spec.media_ids
        carried = self.bundle.ids
        missing = sorted(named - carried)
        if missing:
            raise ValueError(
                f"{self.spec.id}: the film names media the bundle does not carry: "
                f"{', '.join(missing)}"
            )
        spare = sorted(carried - named)
        if spare:
            raise ValueError(
                f"{self.spec.id}: the bundle carries media no scene names: {', '.join(spare)}"
            )

    @property
    def cited_ids(self) -> frozenset[str]:
        """Every source id the film claims to be about. TASK-706 checks these are real."""
        return frozenset(citation.id for scene in self.spec.scenes for citation in scene.cites)


#: What the ledger is called when it travels. A fixed name on purpose: the person opening this
#: folder in fifteen years is not reading our documentation.
PROVENANCE_FILENAME = "provenance.json"


class ProvenanceStatus(StrEnum):
    """The verdict on one citation, after someone went and looked.

    There is deliberately no `FOREIGN` status. A citation that resolves to another family's
    row is recorded as `MISSING`, with the same wording an unknown id gets, mirroring the rule
    the vault and the voice-note reader already follow: a distinct answer for "it exists, but
    not for you" is a way of confirming that another family's recording exists.

    `ALTERED` is the one that earns this whole type. A row that is present but whose bytes no
    longer hash to what was measured is not a missing file - it is a file that changed after
    the film was planned, and the difference matters to whoever has to work out why later.
    """

    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    ALTERED = "ALTERED"


@dataclass(frozen=True, slots=True)
class ProvenanceEntry:
    """One citation, and what was found when it was followed."""

    scene_id: str
    scene_kind: SceneKind
    citation: Citation
    status: ProvenanceStatus
    detail: str = ""
    content_hash: str = ""

    @property
    def is_verified(self) -> bool:
        return self.status is ProvenanceStatus.VERIFIED

    @property
    def key(self) -> tuple[str, str, str]:
        """What this entry is an answer about: a scene, and one citation within it."""
        return (self.scene_id, self.citation.kind.value, self.citation.id)

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "scene_id": self.scene_id,
            "scene_kind": self.scene_kind.value,
            "cites": self.citation.to_dict(),
            "status": self.status.value,
        }
        if self.detail:
            record["detail"] = self.detail
        if self.content_hash:
            record["content_hash"] = self.content_hash
        return record


@dataclass(frozen=True, slots=True)
class Provenance:
    """Every citation in a film, followed back to the archive, one line each.

    This is a *ledger*, not a check that returns a boolean: it records the verdict on every
    citation including the ones that passed, because the value of the artifact fifteen years
    from now is that it lists what the film was made of, not that it once said "ok".
    """

    film_id: str
    family_id: FamilyId
    verified_at: datetime
    entries: tuple[ProvenanceEntry, ...] = ()

    @property
    def unverified(self) -> tuple[ProvenanceEntry, ...]:
        return tuple(entry for entry in self.entries if not entry.is_verified)

    @property
    def is_clean(self) -> bool:
        return not self.unverified

    @property
    def keys(self) -> frozenset[tuple[str, str, str]]:
        return frozenset(entry.key for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "film_id": self.film_id,
            "family_id": str(self.family_id),
            "verified_at": self.verified_at.isoformat(),
            "citation_count": len(self.entries),
            "unverified_count": len(self.unverified),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class FilmPackage:
    """What ships to whatever draws the film: the arithmetic, the files, and the receipts.

    Deliberately not a video and deliberately not a path. A package can be inspected, diffed,
    and handed to a renderer on a machine the family is free to turn off.

    The `provenance` field is required, and the checks below are the point of this type. A
    package refuses to exist unless every citation in the film has been followed and found,
    and unless the ledger covers exactly the film's citations - no scene skipped, no entry
    about a scene that is not in the film. Making the ledger optional, or advisory, would put
    the guarantee back where it was: in whichever code path happened to build the spec.
    """

    draft: FilmDraft
    film: CompiledFilm
    provenance: Provenance

    def __post_init__(self) -> None:
        claimed = frozenset(
            (scene.id, citation.kind.value, citation.id)
            for scene in self.spec.scenes
            for citation in scene.cites
        )
        unchecked = sorted(claimed - self.provenance.keys)
        if unchecked:
            scene_id, kind, cited = unchecked[0]
            raise ValueError(
                f"{self.spec.id}: nobody checked that {scene_id} cites a real {kind} "
                f"({cited}); a ledger with a gap in it is not a ledger"
            )
        invented = sorted(self.provenance.keys - claimed)
        if invented:
            scene_id, kind, cited = invented[0]
            raise ValueError(
                f"{self.spec.id}: the ledger vouches for {kind} {cited} in {scene_id}, "
                f"which this film does not cite"
            )
        failed = self.provenance.unverified
        if failed:
            first = failed[0]
            raise ValueError(
                f"{self.spec.id}: {first.scene_id} cites {first.citation.kind.value} "
                f"{first.citation.id}, which is {first.status.value.lower()}"
            )

    @property
    def spec(self) -> FilmSpec:
        return self.draft.spec

    @property
    def bundle(self) -> MediaBundle:
        return self.draft.bundle

    def to_dict(self) -> dict[str, Any]:
        return {
            "film": self.film.to_dict(),
            "bundle": self.bundle.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


# ============================================================================
# Render Budget & Up-Front Ceilings (PRD 8.2, PRD 57, TASK-1205)
# ============================================================================

MAX_ANNUAL_FILM_DURATION_SECONDS = 720.0  # 12 minutes max
MAX_SCENE_COUNT = 60
MAX_SINGLE_SCENE_SECONDS = 180.0  # 3 minutes max for a single scene
MAX_BUNDLE_MEDIA_COUNT = 150
MAX_BUNDLE_BYTE_SIZE = 1024 * 1024 * 1024  # 1 GB
ESTIMATED_SECONDS_PER_SCENE_RENDER = 10.0
MAX_TOTAL_RENDER_TIME_SECONDS = 600.0  # 10 minutes ceiling on compilation


@dataclass(frozen=True, slots=True)
class RenderBudget:
    """A ceiling on time and cost, checked before the first frame (PRD 8.2, PRD 57).

    A film that would take an hour is refused up front with a sentence, not discovered
    half-rendered.
    """

    max_duration_seconds: float = MAX_ANNUAL_FILM_DURATION_SECONDS
    max_scenes: int = MAX_SCENE_COUNT
    max_single_scene_seconds: float = MAX_SINGLE_SCENE_SECONDS
    max_media_count: int = MAX_BUNDLE_MEDIA_COUNT
    max_total_bytes: int = MAX_BUNDLE_BYTE_SIZE
    max_estimated_render_seconds: float = MAX_TOTAL_RENDER_TIME_SECONDS

    def check_spec(self, spec: FilmSpec) -> None:
        """Validate spec against budget limits before compilation."""
        if len(spec.scenes) > self.max_scenes:
            raise ValueError(
                f"This film contains {len(spec.scenes)} scenes, which exceeds the limit "
                f"of {self.max_scenes} scenes."
            )
        if len(spec.media_ids) > self.max_media_count:
            raise ValueError(
                f"This film references {len(spec.media_ids)} media files, which exceeds "
                f"the limit of {self.max_media_count}."
            )

    def check_compiled(self, film: CompiledFilm) -> None:
        """Validate compiled timeline arithmetic against budget limits."""
        if len(film.scenes) > self.max_scenes:
            raise ValueError(
                f"This film contains {len(film.scenes)} scenes, which exceeds the limit "
                f"of {self.max_scenes} scenes."
            )
        if film.duration_seconds > self.max_duration_seconds:
            duration_mins = film.duration_seconds / 60.0
            max_mins = self.max_duration_seconds / 60.0
            raise ValueError(
                f"This film runs for {duration_mins:.1f} minutes, which exceeds the maximum "
                f"allowed duration of {max_mins:.1f} minutes."
            )
        for scene in film.scenes:
            if scene.visual_seconds > self.max_single_scene_seconds:
                raise ValueError(
                    f"Scene '{scene.id}' runs for {scene.visual_seconds:.1f}s, which exceeds "
                    f"the maximum single scene limit of {self.max_single_scene_seconds:.1f}s."
                )

        estimated_render = len(film.scenes) * ESTIMATED_SECONDS_PER_SCENE_RENDER
        if estimated_render > self.max_estimated_render_seconds:
            raise ValueError(
                f"Estimated compilation time ({estimated_render:.0f}s) exceeds the maximum "
                f"render budget of {self.max_estimated_render_seconds:.0f}s."
            )

    def check_package(self, package: FilmPackage) -> None:
        """Validate entire package (arithmetic, bundle, media size) before starting renderer."""
        self.check_compiled(package.film)
        if len(package.bundle.items) > self.max_media_count:
            raise ValueError(
                f"The media bundle carries {len(package.bundle.items)} items, which exceeds "
                f"the budget limit of {self.max_media_count}."
            )
        if package.bundle.byte_size > self.max_total_bytes:
            mb = package.bundle.byte_size / (1024 * 1024)
            max_mb = self.max_total_bytes / (1024 * 1024)
            raise ValueError(
                f"The media bundle is {mb:.1f} MB, which exceeds the budget ceiling "
                f"of {max_mb:.0f} MB."
            )
