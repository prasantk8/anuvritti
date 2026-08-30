"""Composing a film out of a family's own year (PRD 15, 23, 34).

This is the module where the product either keeps its promise or quietly stops keeping it,
because this is where a film gets its *content*. Everything downstream - the compiler, the
renderer - only arranges what this module chose. Three choices are made here, and each one
is made the boring way on purpose.

**Every scene comes from a row.** A scene is built from a `Moment` and the `Spark` it came
from, and it cites both by id. There is no code path in this module that produces a scene
from a template, a season, a summary or a nice idea, which is what makes an invented memory
expensive to add later rather than one commit away.

**A voice is measured or it is not used.** A `Moment` carries an `audio_media_id`; the length
of that audio lives on the `VoiceNote` that was kept when the recording arrived. If the
recording has no measured length, this module refuses the film and names the moment. It does
not estimate from the transcript, and - the tempting one - it does not silently drop the audio
and carry on, because a film that quietly leaves out a parent's voice is indistinguishable
from a film that never had it.

**A caption is a quotation.** Captions in a film are read as "this is what they said", so only
a transcript a person wrote or corrected becomes one. A machine transcript stays where PRD 8.7
put it: an index for a search box. It is better for a film to be uncaptioned than for a child
to read a sentence their father never said, rendered in a serif face, over a photograph of
themselves.

**A machine is a narrator of last resort, and only between the memories.** There is a
`Narrator` port and this module will use it - for the title card and the sign-off, and for
nothing else, because those are the only two scenes in a film that claim nothing. It is
optional and it defaults to absent: with no narrator wired, a film opens in silence, which is
what this product ships as. When one *is* wired, a line that fails to synthesise becomes
silence rather than an estimate, and the asymmetry with the rule above is deliberate - the
rule that refuses to quietly drop a parent's recording is the same rule that shrugs at losing
a machine's sentence, because one of them is somebody's father and the other is a
synthesiser reading four fixed words.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from anuvritti.application.ports import (
    FamilyRepository,
    FilmCompiler,
    LittleThingRepository,
    MediaStore,
    MomentRepository,
    Narrator,
    SparkRepository,
    VoiceNoteRepository,
)
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.domain.family import ChildProfile, Family
from anuvritti.domain.film import (
    CLOSING_LINE,
    DEFAULT_TARGET_SECONDS,
    DEFAULT_TOLERANCE_SECONDS,
    BundledMedia,
    Citation,
    CitationKind,
    ConnectiveLine,
    FilmDraft,
    FilmPackage,
    FilmScene,
    FilmSpec,
    MediaBundle,
    Provenance,
    SceneKind,
    SceneVoice,
)
from anuvritti.domain.moment import Moment
from anuvritti.domain.presence import LittleThing
from anuvritti.domain.spark import Spark
from anuvritti.domain.voice import VoiceNote
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, IdGenerator, MediaId, MemberId
from anuvritti.shared.result import Err, Ok, Result

#: How long a scene holds when nobody is talking. Long enough to actually look at a
#: photograph, short enough that a film of forty of them is not an endurance test. It is a
#: floor, not a length: a scene with a voice over it holds for as long as the voice does.
SILENT_HOLD_SECONDS = 4.5

#: The title card and the last card. Short - a family already knows whose film this is.
OPENING_SECONDS = 3.0
CLOSING_SECONDS = 4.0

#: `CLOSING_LINE` is re-exported from the domain, where it sits next to the types that make it
#: true. It is not a slogan: `FilmScene` refuses to hold a scene that would make it false.
__all__ = [
    "CLOSING_LINE",
    "CompileFilmUseCase",
    "ComposeFilmCommand",
    "ComposeFilmUseCase",
    "TheYearCommand",
    "TheYearUseCase",
]


@dataclass(frozen=True, slots=True)
class ComposeFilmCommand:
    """Which life, whose, and over what stretch of it.

    `since`/`until` are inclusive and both optional; leaving them out means the whole archive,
    which is the right default for a first film and the wrong one for a birthday capsule.
    """

    family_id: FamilyId
    actor_id: MemberId
    child_id: ChildId | None = None
    title: str | None = None
    since: date | None = None
    until: date | None = None
    target_seconds: float = DEFAULT_TARGET_SECONDS
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS
    include_little_things: bool = False
    film_id: str | None = None


class ComposeFilmUseCase:
    """Moments in, a `FilmDraft` out. Nothing is rendered and nothing is written."""

    def __init__(
        self,
        *,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        voice_notes: VoiceNoteRepository,
        media: MediaStore,
        ids: IdGenerator,
        narrator: Narrator | None = None,
        little_things: LittleThingRepository | None = None,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._voice_notes = voice_notes
        self._media = media
        self._ids = ids
        self._narrator = narrator
        self._little_things = little_things

    def execute(self, command: ComposeFilmCommand) -> Result[FilmDraft, DomainError]:
        family_result = self._families.get(command.family_id)
        if family_result.is_err():
            return Err(family_result.unwrap_err())
        family = family_result.unwrap()

        actor = family.member(command.actor_id)
        if actor.is_err():
            return Err(actor.unwrap_err())

        child: ChildProfile | None = None
        if command.child_id is not None:
            found = family.child(command.child_id)
            if found.is_err():
                return Err(found.unwrap_err())
            child = found.unwrap()

        material = self._material(command)
        if material.is_err():
            return Err(material.unwrap_err())
        pairs = material.unwrap()
        little_things = self._little_things_in(command)
        if little_things.is_err():
            return Err(little_things.unwrap_err())
        small = little_things.unwrap()
        if not pairs and not small:
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    "there is nothing in that stretch of time yet - a film needs a moment "
                    "that actually happened",
                    {"family_id": str(command.family_id)},
                )
            )

        scenes: list[FilmScene] = []
        for moment, spark in pairs:
            built = self._scene(moment, spark, command.family_id)
            if built.is_err():
                return Err(built.unwrap_err())
            scenes.append(built.unwrap())

        for little_thing in small:
            built = self._little_thing_scene(little_thing, command.family_id)
            if built.is_err():
                return Err(built.unwrap_err())
            scenes.append(built.unwrap())

        scenes.sort(key=lambda scene: _scene_day(scene, pairs, small))

        evidence_days = [moment.happened_on for moment, _ in pairs]
        evidence_days.extend(item.created_at.date() for item in small)
        title = command.title or _title(family, child, evidence_days)
        spec = FilmSpec(
            id=command.film_id or f"film-{self._ids.new_id()}",
            family_id=command.family_id,
            child_id=command.child_id,
            title=title,
            scenes=(
                _opening(
                    title,
                    evidence_days,
                    self._connective(ConnectiveLine.OPENING, command.family_id),
                ),
                *scenes,
                _closing(len(scenes), self._connective(ConnectiveLine.CLOSING, command.family_id)),
            ),
            target_seconds=command.target_seconds,
            tolerance_seconds=command.tolerance_seconds,
        )

        bundle = self._bundle(spec, command.family_id)
        if bundle.is_err():
            return Err(bundle.unwrap_err())
        return Ok(FilmDraft(spec=spec, bundle=bundle.unwrap()))

    # ------------------------------------------------------------------ material
    def _material(
        self, command: ComposeFilmCommand
    ) -> Result[list[tuple[Moment, Spark]], DomainError]:
        """The moments in the window, each with the spark it came from.

        The spark is not decoration. It carries the child the moment is about - a `Moment` on
        its own does not know - and its title is the only sentence in the scene that a person
        actually wrote.
        """
        listed = self._moments.list_for_family(command.family_id)
        if listed.is_err():
            return Err(listed.unwrap_err())

        pairs: list[tuple[Moment, Spark]] = []
        for moment in listed.unwrap():
            if not _within(moment.happened_on, command.since, command.until):
                continue
            found = self._sparks.get(moment.spark_id)
            if found.is_err():
                return Err(found.unwrap_err())
            spark = found.unwrap()
            if command.child_id is not None and spark.subject_child_id != command.child_id:
                continue
            pairs.append((moment, spark))

        pairs.sort(key=lambda pair: (pair[0].happened_on, pair[0].created_at, str(pair[0].id)))
        return Ok(pairs)

    def _little_things_in(
        self, command: ComposeFilmCommand
    ) -> Result[list[LittleThing], DomainError]:
        if not command.include_little_things or self._little_things is None:
            return Ok([])
        listed = self._little_things.list_for_family(command.family_id)
        if listed.is_err():
            return Err(listed.unwrap_err())
        things = [
            item
            for item in listed.unwrap()
            if _within(item.created_at.date(), command.since, command.until)
            and (command.child_id is None or item.subject_child_id == command.child_id)
        ]
        things.sort(key=lambda item: (item.created_at, str(item.id)))
        return Ok(things)

    # --------------------------------------------------------------------- scenes
    def _scene(
        self, moment: Moment, spark: Spark, family_id: FamilyId
    ) -> Result[FilmScene, DomainError]:
        cites = [
            Citation(CitationKind.MOMENT, str(moment.id)),
            Citation(CitationKind.SPARK, str(moment.spark_id)),
        ]

        voice = SceneVoice.silent(0.0)
        kind = SceneKind.MOMENT
        if moment.audio_media_id is not None:
            heard = self._voice(MediaId(str(moment.audio_media_id)), moment, family_id)
            if heard.is_err():
                return Err(heard.unwrap_err())
            note = heard.unwrap()
            voice = SceneVoice.recorded(
                media_id=note.media_id,
                seconds=note.duration_seconds,
                text=_caption(note),
            )
            kind = SceneKind.VOICE
            cites.append(Citation(CitationKind.VOICE_NOTE, str(note.media_id)))

        if moment.photo_media_id is not None:
            cites.append(Citation(CitationKind.MEDIA, str(moment.photo_media_id)))

        return Ok(
            FilmScene(
                id=f"moment-{moment.id}",
                kind=kind,
                heading=spark.title,
                body=moment.reflection or "",
                voice=voice,
                cites=tuple(cites),
                min_seconds=SILENT_HOLD_SECONDS,
            )
        )

    def _voice(
        self, media_id: MediaId, moment: Moment, family_id: FamilyId
    ) -> Result[VoiceNote, DomainError]:
        """The recording's *measured* length, or a refusal that names the moment.

        The alternative - drop the audio, keep the picture, compile a silent scene - is the
        one that would never be noticed. It produces a perfectly good film with a parent
        missing from it, and nothing anywhere saying so.
        """
        unmeasured = DomainError(
            ErrorCode.FILM_NOT_COMPILABLE,
            "this moment has audio that nobody measured, and the film will not guess how "
            "long a person spoke",
            {"moment_id": str(moment.id), "media_id": str(media_id)},
        )
        found = self._voice_notes.get(media_id)
        if found.is_err():
            return Err(unmeasured)
        note = found.unwrap()
        if note.family_id != family_id:
            # Deliberately the same answer an unknown id gets, for the reason given in
            # `KeepVoiceNoteUseCase`: a distinct one confirms the recording exists.
            return Err(unmeasured)
        return Ok(note)

    def _little_thing_scene(
        self, item: LittleThing, family_id: FamilyId
    ) -> Result[FilmScene, DomainError]:
        cites = [Citation(CitationKind.LITTLE_THING, str(item.id))]
        voice = SceneVoice.silent(0.0)
        if item.audio_media_id is not None:
            # A Little Thing's recording obeys the same rule as a Moment's: it is used only
            # when the bytes have a measured VoiceNote beside them.
            found = self._voice_notes.get(MediaId(item.audio_media_id))
            if found.is_err() or found.unwrap().family_id != family_id:
                return Err(
                    DomainError(
                        ErrorCode.FILM_NOT_COMPILABLE,
                        "this little thing has audio that nobody measured, and the film will "
                        "not guess how long a person spoke",
                        {"little_thing_id": str(item.id), "media_id": item.audio_media_id},
                    )
                )
            note = found.unwrap()
            voice = SceneVoice.recorded(
                media_id=note.media_id, seconds=note.duration_seconds, text=_caption(note)
            )
            cites.append(Citation(CitationKind.VOICE_NOTE, str(note.media_id)))
        return Ok(
            FilmScene(
                id=f"little-thing-{item.id}",
                kind=SceneKind.LITTLE_THING,
                heading="A little thing",
                body=item.text or "",
                voice=voice,
                cites=tuple(cites),
                min_seconds=SILENT_HOLD_SECONDS,
            )
        )

    # ---------------------------------------------------------------- connective
    def _connective(self, line: ConnectiveLine, family_id: FamilyId) -> SceneVoice:
        """A title card's voice, if there is a narrator to give it one. Otherwise silence.

        Note what is *not* here: no branch that says "if synthesis failed, fall back to
        estimating the length from the words". There is nowhere to put such a branch, because
        `SceneVoice.synthetic` has no constructor that omits the file. A line either got
        spoken into something measurable or the card holds in silence, and the film is no
        worse for it.
        """
        if self._narrator is None:
            return SceneVoice.silent(0.0)
        spoken = self._narrator.speak(line, family_id=family_id)
        if spoken.is_err():
            return SceneVoice.silent(0.0)
        speech = spoken.unwrap()
        return SceneVoice.synthetic(line=line, media_id=speech.media_id, seconds=speech.seconds)

    # --------------------------------------------------------------------- bundle
    def _bundle(self, spec: FilmSpec, family_id: FamilyId) -> Result[MediaBundle, DomainError]:
        """Exactly the files the spec names, described from the store that holds them.

        Sorted by id so the same year composes to the same bundle twice, which is what lets a
        renderer cache anything at all.
        """
        items: list[BundledMedia] = []
        for media_id in sorted(spec.media_ids):
            described = self._media.describe(MediaId(media_id))
            if described.is_err():
                return Err(_no_such_file(spec, media_id))
            media = described.unwrap()
            if media.family_id != family_id:
                return Err(_no_such_file(spec, media_id))
            items.append(
                BundledMedia(
                    id=media.id,
                    kind=media.kind,
                    mime_type=media.mime_type,
                    byte_size=media.byte_size,
                    content_hash=media.content_hash,
                )
            )
        return Ok(MediaBundle(tuple(items)))


class CompileFilmUseCase:
    """Compose, verify, then compile. What comes back is a package, never a video.

    The order is the interesting part. Verification happens *before* the compiler is asked
    for anything, so a film that cites something that is not there fails while the failure is
    still cheap and still legible - "scene moment-4 cites MEDIA med-9, which is missing" -
    rather than at the far end, on the machine with the browser, where the only available
    behaviours are to crash or to draw a hole.

    This is also the only place in the application layer that touches a `FilmCompiler`, and it
    touches it through the port - so the composition root that boots the family's always-on
    server still has no reason to import an adapter that could grow a browser. See
    `FilmCompiler` in the ports module for what that buys.
    """

    def __init__(
        self,
        *,
        compose: ComposeFilmUseCase,
        verify: VerifyProvenanceUseCase,
        compiler: FilmCompiler,
    ) -> None:
        self._compose = compose
        self._verify = verify
        self._compiler = compiler

    def execute(self, command: ComposeFilmCommand) -> Result[FilmPackage, DomainError]:
        drafted = self._compose.execute(command)
        if drafted.is_err():
            return Err(drafted.unwrap_err())
        draft = drafted.unwrap()

        checked = self._verify.execute(draft)
        if checked.is_err():
            return Err(checked.unwrap_err())
        provenance = checked.unwrap()
        if not provenance.is_clean:
            return Err(_unfounded(draft.spec, provenance))

        compiled = self._compiler.compile(draft.spec)
        if compiled.is_err():
            return Err(compiled.unwrap_err())
        return Ok(FilmPackage(draft=draft, film=compiled.unwrap(), provenance=provenance))


@dataclass(frozen=True, slots=True)
class TheYearCommand:
    """The one birthday-to-birthday edition belonging to a child."""

    family_id: FamilyId
    actor_id: MemberId
    child_id: ChildId
    birthday_year: int


class TheYearUseCase:
    """Compile one stable annual film from the child's real birthday boundary."""

    def __init__(self, *, families: FamilyRepository, compile_film: CompileFilmUseCase) -> None:
        self._families = families
        self._compile_film = compile_film

    def execute(self, command: TheYearCommand) -> Result[FilmPackage, DomainError]:
        found = self._families.get(command.family_id)
        if found.is_err():
            return Err(found.unwrap_err())
        family = found.unwrap()
        actor = family.member(command.actor_id)
        if actor.is_err():
            return Err(actor.unwrap_err())
        child = family.child(command.child_id)
        if child.is_err():
            return Err(child.unwrap_err())
        profile = child.unwrap()
        since = _birthday_in(profile, command.birthday_year)
        until = _birthday_in(profile, command.birthday_year + 1) - timedelta(days=1)
        edition = f"{command.birthday_year}-{command.birthday_year + 1}"
        return self._compile_film.execute(
            ComposeFilmCommand(
                family_id=command.family_id,
                actor_id=command.actor_id,
                child_id=command.child_id,
                title=f"{profile.display_name}, {edition}",
                since=since,
                until=until,
                include_little_things=True,
                film_id=f"the-year-{command.child_id}-{command.birthday_year}",
            )
        )


# ------------------------------------------------------------------------ helpers
def _within(day: date, since: date | None, until: date | None) -> bool:
    if since is not None and day < since:
        return False
    return not (until is not None and day > until)


def _caption(note: VoiceNote) -> str:
    """A quotation, or nothing. A machine's reading of a recording is not a quotation."""
    transcript = note.transcript
    if transcript is None or transcript.is_machine_made:
        return ""
    return transcript.text


def _unfounded(spec: FilmSpec, provenance: Provenance) -> DomainError:
    """A film that cites something nobody could find does not get made today.

    The message names one failure rather than all of them because the first one is what a
    person will act on, and the count tells them whether they are looking at a typo or at an
    archive that has lost something. `details` carries the id so a log is actionable without
    the film in front of you.
    """
    first = provenance.unverified[0]
    return DomainError(
        ErrorCode.FILM_NOT_COMPILABLE,
        f"{first.scene_id} cites a {first.citation.kind.value.lower().replace('_', ' ')} that "
        f"is {first.status.value.lower()}, and a film does not get to claim something nobody "
        f"can find",
        {
            "film_id": spec.id,
            "scene_id": first.scene_id,
            "cites": first.citation.id,
            "status": first.status.value,
            "unverified_count": len(provenance.unverified),
        },
    )


def _no_such_file(spec: FilmSpec, media_id: str) -> DomainError:
    return DomainError(
        ErrorCode.FILM_NOT_COMPILABLE,
        "the film names a file that is not in this family's archive",
        {"spec_id": spec.id, "media_id": media_id},
    )


def _title(family: Family, child: ChildProfile | None, days: Sequence[date]) -> str:
    """Named after what is actually in it, not after the window that was asked for.

    A parent who asks for 2026 in March gets "Aarav, 2026" and not a film that claims to be
    a year when it is eleven weeks.
    """
    who = child.display_name if child is not None else family.name
    years = sorted({day.year for day in days})
    span = str(years[0]) if years[0] == years[-1] else f"{years[0]}-{years[-1]}"
    return f"{who}, {span}"


def _opening(title: str, days: Sequence[date], voice: SceneVoice) -> FilmScene:
    first = min(days)
    last = max(days)
    return FilmScene(
        id="opening",
        kind=SceneKind.OPENING,
        heading=title,
        body=first.isoformat() if first == last else f"{first.isoformat()} - {last.isoformat()}",
        voice=voice,
        min_seconds=OPENING_SECONDS,
    )


def _closing(scene_count: int, voice: SceneVoice) -> FilmScene:
    kept = "1 moment" if scene_count == 1 else f"{scene_count} moments"
    return FilmScene(
        id="closing",
        kind=SceneKind.CLOSING,
        heading=kept,
        body=CLOSING_LINE,
        voice=voice,
        min_seconds=CLOSING_SECONDS,
    )


def _birthday_in(child: ChildProfile, year: int) -> date:
    """The anniversary used by `age_years`, including its March-1 leap-day rule."""
    try:
        return child.date_of_birth.replace(year=year)
    except ValueError:
        return date(year, 3, 1)


def _scene_day(
    scene: FilmScene,
    moments: Sequence[tuple[Moment, Spark]],
    little_things: Sequence[LittleThing],
) -> tuple[date, str]:
    if scene.kind is SceneKind.LITTLE_THING:
        item = next(item for item in little_things if scene.id == f"little-thing-{item.id}")
        return item.created_at.date(), scene.id
    moment = next(moment for moment, _ in moments if scene.id == f"moment-{moment.id}")
    return moment.happened_on, scene.id
