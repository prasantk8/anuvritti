"""Following every citation in a film back to the archive (PRD 8.7, 47).

`FilmScene` already guarantees that an evidence scene *has* a citation, and
`ComposeFilmUseCase` builds every citation out of a row it just read. Both are true, and
neither is what this module is for.

The guarantee those two provide is a property of one code path. It holds until the day
someone adds a second way to build a spec - a template, an import, a "highlights of the
year" generator, a fixture that leaked into production - and it holds silently, so the day
it stops holding looks exactly like the day before. A film that cites `spk-9` is
indistinguishable from a film that cites a Spark, unless somebody goes and looks.

So this module goes and looks, and it is deliberately built as though the film came from a
stranger:

**Nothing the composer consulted counts as evidence.** A media citation is not verified by
asking the catalogue the same question the bundle already asked it; the bytes are read and
re-hashed. A row that says a photograph exists is not a photograph.

**"Not found" is a verdict; "could not look" is not.** A repository that returns
`SPARK_NOT_FOUND` has answered the question. A repository that returns anything else has
failed to answer it, and recording that as MISSING would put "your Spark does not exist" in
a ledger when the truth was that a disk was unreachable. Those errors propagate, and the
film simply does not get built today.

**A citation into another family is recorded as MISSING**, in the same words an unknown id
gets, for the reason the vault reader already refuses to distinguish them.
"""

from __future__ import annotations

from anuvritti.application.ports import (
    LittleThingRepository,
    MediaStore,
    MomentRepository,
    SparkRepository,
    VoiceNoteRepository,
)
from anuvritti.application.sound import SoundBedCatalogue, get_default_sound_catalogue
from anuvritti.domain.film import (
    Citation,
    CitationKind,
    FilmDraft,
    FilmScene,
    Provenance,
    ProvenanceEntry,
    ProvenanceStatus,
)
from anuvritti.shared.clock import Clock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId, MomentId, SparkId
from anuvritti.shared.result import Err, Ok, Result

#: What a citation that resolves to nothing is told, whether the id is unknown or belongs to
#: another family. One sentence for both cases, on purpose - see the module docstring.
NOT_IN_ARCHIVE = "not in this family's archive"

#: The error codes that mean "asked and answered: there is no such row". Anything else from a
#: repository is a failure to look, and is propagated rather than written down as a verdict.
_ABSENT: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.SPARK_NOT_FOUND,
        ErrorCode.MOMENT_NOT_FOUND,
        ErrorCode.MEDIA_NOT_FOUND,
    }
)


class VerifyProvenanceUseCase:
    """Reads a `FilmDraft` and returns the ledger of what its citations actually point at.

    Returns a `Provenance` rather than a pass/fail because the ledger is the deliverable: it
    ships beside the film as `provenance.json`, and a child who wants to know where a scene
    came from is owed the identifier, not a reassurance. Refusing the film is somebody else's
    job - `FilmPackage` will not be constructed around a ledger with a failure in it.
    """

    def __init__(
        self,
        *,
        sparks: SparkRepository,
        moments: MomentRepository,
        voice_notes: VoiceNoteRepository,
        little_things: LittleThingRepository,
        media: MediaStore,
        sound_beds: SoundBedCatalogue | None = None,
        clock: Clock,
    ) -> None:
        self._sparks = sparks
        self._moments = moments
        self._voice_notes = voice_notes
        self._little_things = little_things
        self._media = media
        self._sound_beds = sound_beds if sound_beds is not None else get_default_sound_catalogue()
        self._clock = clock

    def execute(self, draft: FilmDraft) -> Result[Provenance, DomainError]:
        family_id = draft.spec.family_id
        hashes = {str(item.id): item.content_hash for item in draft.bundle.items}

        entries: list[ProvenanceEntry] = []
        for scene in draft.spec.scenes:
            for citation in scene.cites:
                checked = self._check(citation, family_id=family_id, hashes=hashes)
                if checked.is_err():
                    return Err(checked.unwrap_err())
                entries.append(_entry(scene, citation, checked.unwrap()))

        return Ok(
            Provenance(
                film_id=draft.spec.id,
                family_id=family_id,
                verified_at=self._clock.now(),
                entries=tuple(entries),
            )
        )

    # ------------------------------------------------------------------ one citation
    def _check(
        self, citation: Citation, *, family_id: FamilyId, hashes: dict[str, str]
    ) -> Result[_Verdict, DomainError]:
        match citation.kind:
            case CitationKind.SPARK:
                return self._spark(citation.id, family_id)
            case CitationKind.MOMENT:
                return self._moment(citation.id, family_id)
            case CitationKind.VOICE_NOTE:
                return self._voice_note(citation.id, family_id, hashes)
            case CitationKind.LITTLE_THING:
                return self._little_thing(citation.id, family_id)
            case CitationKind.MEDIA:
                return self._media_file(citation.id, family_id, hashes)
            case CitationKind.SOUND_BED:
                return self._sound_bed(citation.id, hashes)

    def _sound_bed(self, cited: str, hashes: dict[str, str]) -> Result[_Verdict, DomainError]:
        found = self._sound_beds.get(cited)
        if found.is_err():
            return _absent_or_raise(found.unwrap_err())
        track = found.unwrap()
        expected = hashes.get(cited, track.content_hash)
        if track.content_hash != expected:
            return Ok(
                _Verdict(
                    ProvenanceStatus.ALTERED,
                    "the sound bed audio has been modified from its approved master",
                    track.content_hash,
                )
            )
        if not track.is_license_clean:
            return Ok(
                _Verdict(
                    ProvenanceStatus.ALTERED,
                    "the sound bed track is not licence-clean",
                    track.content_hash,
                )
            )
        return Ok(
            _Verdict(
                ProvenanceStatus.VERIFIED,
                f"Licence: {track.license} ({track.title})",
                track.content_hash,
            )
        )

    def _spark(self, cited: str, family_id: FamilyId) -> Result[_Verdict, DomainError]:
        found = self._sparks.get(SparkId(cited))
        if found.is_err():
            return _absent_or_raise(found.unwrap_err())
        return Ok(_found_if(found.unwrap().family_id == family_id))

    def _moment(self, cited: str, family_id: FamilyId) -> Result[_Verdict, DomainError]:
        found = self._moments.get(MomentId(cited))
        if found.is_err():
            return _absent_or_raise(found.unwrap_err())
        return Ok(_found_if(found.unwrap().family_id == family_id))

    def _voice_note(
        self, cited: str, family_id: FamilyId, hashes: dict[str, str]
    ) -> Result[_Verdict, DomainError]:
        """Two questions, because a voice note is two things.

        `VoiceNote` is the row carrying the measured length; the id it is keyed on is also a
        real file in the bundle. Checking only the row would verify that somebody once wrote
        down how long a parent spoke, while the recording itself had been replaced - which is
        the worst version of this failure, because the film would still add up.
        """
        found = self._voice_notes.get(MediaId(cited))
        if found.is_err():
            return _absent_or_raise(found.unwrap_err())
        if found.unwrap().family_id != family_id:
            return Ok(_Verdict(ProvenanceStatus.MISSING, NOT_IN_ARCHIVE))
        return self._media_file(cited, family_id, hashes)

    def _little_thing(self, cited: str, family_id: FamilyId) -> Result[_Verdict, DomainError]:
        """No `get` on this repository, so membership of the family's own list is the check.

        Which is the stronger question anyway: "is this one of theirs", asked in one call.
        """
        listed = self._little_things.list_for_family(family_id)
        if listed.is_err():
            return Err(listed.unwrap_err())
        return Ok(_found_if(any(str(thing.id) == cited for thing in listed.unwrap())))

    def _media_file(
        self, cited: str, family_id: FamilyId, hashes: dict[str, str]
    ) -> Result[_Verdict, DomainError]:
        """Read the bytes. A catalogue row is a claim about a file, not a file.

        This is the expensive check and the only one worth having: `_bundle` already asked the
        catalogue, so asking it again would verify that the composer can read its own notes.
        Reading costs one pass over the year's media at compile time, which is where a family
        can still be told, rather than at render time on a machine that will guess or die.
        """
        described = self._media.describe(MediaId(cited))
        if described.is_err():
            return _absent_or_raise(described.unwrap_err())
        media = described.unwrap()
        if media.family_id != family_id:
            return Ok(_Verdict(ProvenanceStatus.MISSING, NOT_IN_ARCHIVE))

        expected = hashes.get(cited, media.content_hash)
        if media.content_hash != expected:
            return Ok(
                _Verdict(
                    ProvenanceStatus.ALTERED,
                    "the stored file is not the one this film was measured against",
                    media.content_hash,
                )
            )

        content = self._media.get(MediaId(cited))
        if content.is_err():
            error = content.unwrap_err()
            if error.code is ErrorCode.CONFLICT:
                return Ok(
                    _Verdict(ProvenanceStatus.ALTERED, "the bytes no longer match their hash")
                )
            if error.code in _ABSENT:
                return Ok(_Verdict(ProvenanceStatus.MISSING, "the row is here, the bytes are not"))
            return Err(error)

        return Ok(_Verdict(ProvenanceStatus.VERIFIED, "", expected))


# ---------------------------------------------------------------------- verdicts
class _Verdict:
    """What one lookup found, before it is attached to the scene that made the claim."""

    __slots__ = ("content_hash", "detail", "status")

    def __init__(self, status: ProvenanceStatus, detail: str = "", content_hash: str = "") -> None:
        self.status = status
        self.detail = detail
        self.content_hash = content_hash


def _found_if(present: bool) -> _Verdict:
    if present:
        return _Verdict(ProvenanceStatus.VERIFIED)
    return _Verdict(ProvenanceStatus.MISSING, NOT_IN_ARCHIVE)


def _absent_or_raise(error: DomainError) -> Result[_Verdict, DomainError]:
    """A "no such row" is an answer. Anything else means the question went unanswered."""
    if error.code in _ABSENT:
        return Ok(_Verdict(ProvenanceStatus.MISSING, NOT_IN_ARCHIVE))
    return Err(error)


def _entry(scene: FilmScene, citation: Citation, verdict: _Verdict) -> ProvenanceEntry:
    return ProvenanceEntry(
        scene_id=scene.id,
        scene_kind=scene.kind,
        citation=citation,
        status=verdict.status,
        detail=verdict.detail,
        content_hash=verdict.content_hash,
    )
