"""TASK-1210: Sound Garden Audio Bed & Provenance (PRD 43, PRD 47).

Verifies:
1. Approved audio beds are licence-clean (CC0/CC-BY/open licence) with master digests.
2. Provenance of sound beds is verified and recorded into provenance.json just like memories.
3. Unapproved or altered sound beds fail provenance verification.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.application.sound import (
    SoundBedTrack,
    StaticSoundBedCatalogue,
    get_default_sound_catalogue,
)
from anuvritti.domain.film import (
    BundledMedia,
    Citation,
    CitationKind,
    FilmDraft,
    FilmScene,
    FilmSpec,
    MediaBundle,
    MediaKind,
    ProvenanceStatus,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.clock import Clock, FrozenClock
from anuvritti.shared.identity import FamilyId, MediaId
from tests.support.fakes import (
    InMemoryLittleThingRepository,
    InMemoryMediaStore,
    InMemoryMomentRepository,
    InMemorySparkRepository,
    InMemoryVoiceNoteRepository,
)


@pytest.fixture
def clock() -> Clock:
    return FrozenClock(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC))


def test_approved_sound_beds_are_license_clean():
    """Every track in the approved sound garden must have clean licensing and master hash."""
    catalogue = get_default_sound_catalogue()
    tracks = catalogue.list_tracks()
    assert len(tracks) >= 3

    for track in tracks:
        assert track.is_license_clean
        assert len(track.license.strip()) > 0
        assert track.license_url.startswith("https://")
        assert len(track.content_hash) == 64
        assert track.duration_seconds > 0.0


def test_sound_bed_provenance_verified(clock: Clock):
    """A film draft citing an approved sound bed produces a VERIFIED provenance entry."""
    catalogue = get_default_sound_catalogue()
    track = catalogue.get("sb-morning-dew-1").unwrap()

    spec = FilmSpec(
        id="film-sb-1",
        family_id=FamilyId("fam-1"),
        title="Spring Afternoon",
        scenes=(
            FilmScene(
                id="scene-intro",
                kind=SceneKind.OPENING,
                heading="Spring Afternoon",
                voice=SceneVoice.silent(3.0),
                cites=(Citation(kind=CitationKind.SOUND_BED, id="sb-morning-dew-1"),),
            ),
        ),
    )

    bundle = MediaBundle(
        items=(
            BundledMedia(
                id=MediaId("sb-morning-dew-1"),
                kind=MediaKind.AUDIO,
                mime_type="audio/wav",
                byte_size=1000,
                content_hash=track.content_hash,
            ),
        )
    )

    draft = FilmDraft(spec=spec, bundle=bundle)

    use_case = VerifyProvenanceUseCase(
        sparks=InMemorySparkRepository(),
        moments=InMemoryMomentRepository(),
        voice_notes=InMemoryVoiceNoteRepository(),
        little_things=InMemoryLittleThingRepository(),
        media=InMemoryMediaStore(),
        sound_beds=catalogue,
        clock=clock,
    )

    result = use_case.execute(draft)
    assert result.is_ok()
    provenance = result.unwrap()

    assert len(provenance.entries) == 1
    entry = provenance.entries[0]
    assert entry.citation.kind == CitationKind.SOUND_BED
    assert entry.citation.id == "sb-morning-dew-1"
    assert entry.status == ProvenanceStatus.VERIFIED
    assert "Licence: CC0-1.0" in entry.detail
    assert entry.content_hash == track.content_hash


def test_missing_sound_bed_marked_missing(clock: Clock):
    """An unknown sound bed citation is flagged MISSING in provenance."""
    spec = FilmSpec(
        id="film-sb-missing",
        family_id=FamilyId("fam-1"),
        title="Unknown Track",
        scenes=(
            FilmScene(
                id="scene-1",
                kind=SceneKind.OPENING,
                heading="Unknown Track",
                voice=SceneVoice.silent(3.0),
                cites=(Citation(kind=CitationKind.SOUND_BED, id="sb-unknown-track"),),
            ),
        ),
    )
    bundle = MediaBundle(
        items=(
            BundledMedia(
                id=MediaId("sb-unknown-track"),
                kind=MediaKind.AUDIO,
                mime_type="audio/wav",
                byte_size=1000,
                content_hash="unknown-hash-999",
            ),
        )
    )
    draft = FilmDraft(spec=spec, bundle=bundle)

    use_case = VerifyProvenanceUseCase(
        sparks=InMemorySparkRepository(),
        moments=InMemoryMomentRepository(),
        voice_notes=InMemoryVoiceNoteRepository(),
        little_things=InMemoryLittleThingRepository(),
        media=InMemoryMediaStore(),
        clock=clock,
    )

    result = use_case.execute(draft)
    assert result.is_ok()
    provenance = result.unwrap()

    assert len(provenance.entries) == 1
    assert provenance.entries[0].status == ProvenanceStatus.MISSING


def test_altered_sound_bed_marked_altered(clock: Clock):
    """A sound bed whose audio hash does not match approved master is flagged ALTERED."""
    catalogue = get_default_sound_catalogue()

    spec = FilmSpec(
        id="film-sb-altered",
        family_id=FamilyId("fam-1"),
        title="Altered Audio Bed",
        scenes=(
            FilmScene(
                id="scene-1",
                kind=SceneKind.OPENING,
                heading="Altered Audio",
                voice=SceneVoice.silent(3.0),
                cites=(Citation(kind=CitationKind.SOUND_BED, id="sb-morning-dew-1"),),
            ),
        ),
    )

    # Bundle specifies an altered hash
    bundle = MediaBundle(
        items=(
            BundledMedia(
                id=MediaId("sb-morning-dew-1"),
                kind=MediaKind.AUDIO,
                mime_type="audio/wav",
                byte_size=1000,
                content_hash="bad-altered-hash-1234567890",
            ),
        )
    )

    draft = FilmDraft(spec=spec, bundle=bundle)

    use_case = VerifyProvenanceUseCase(
        sparks=InMemorySparkRepository(),
        moments=InMemoryMomentRepository(),
        voice_notes=InMemoryVoiceNoteRepository(),
        little_things=InMemoryLittleThingRepository(),
        media=InMemoryMediaStore(),
        sound_beds=catalogue,
        clock=clock,
    )

    result = use_case.execute(draft)
    assert result.is_ok()
    provenance = result.unwrap()

    assert len(provenance.entries) == 1
    assert provenance.entries[0].status == ProvenanceStatus.ALTERED


def test_sound_bed_track_to_dict_and_catalogue_verify():
    """Verify track serialization and catalogue verification methods."""
    catalogue = get_default_sound_catalogue()
    track = catalogue.get("sb-morning-dew-1").unwrap()

    payload = track.to_dict()
    assert payload["id"] == "sb-morning-dew-1"
    assert payload["license"] == "CC0-1.0"
    assert payload["is_license_clean"] is True

    # 1. verify_track OK
    ok_res = catalogue.verify_track("sb-morning-dew-1", track.content_hash)
    assert ok_res.is_ok()

    # 2. verify_track missing
    missing_res = catalogue.verify_track("sb-non-existent")
    assert missing_res.is_err()

    # 3. verify_track hash mismatch
    bad_hash_res = catalogue.verify_track("sb-morning-dew-1", "expected-different-hash")
    assert bad_hash_res.is_err()

    # 4. verify_track not licence clean
    unclean_track = SoundBedTrack(
        id="sb-unclean",
        title="Unclean",
        artist="Artist",
        license="All-Rights-Reserved",
        license_url="http://example.com",
        content_hash="hash",
        duration_seconds=10.0,
        is_license_clean=False,
    )
    custom_cat = StaticSoundBedCatalogue((unclean_track,))
    unclean_res = custom_cat.verify_track("sb-unclean")
    assert unclean_res.is_err()
