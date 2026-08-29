"""The Sound Garden: Licence-clean audio bed for family films (PRD 43, PRD 47, TASK-1210).

Every music and audio track in a film must be strictly licence-clean,
with its provenance recorded in provenance.json alongside real memories.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class SoundBedTrack:
    """A licence-clean audio bed track from the approved sound catalogue."""

    id: str
    title: str
    artist: str
    license: str
    license_url: str
    content_hash: str
    duration_seconds: float
    tags: tuple[str, ...] = ()
    is_license_clean: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "license": self.license,
            "license_url": self.license_url,
            "content_hash": self.content_hash,
            "duration_seconds": round(self.duration_seconds, 3),
            "tags": list(self.tags),
            "is_license_clean": self.is_license_clean,
        }


# Canonical approved catalogue of licence-clean sound beds
APPROVED_SOUND_BEDS: tuple[SoundBedTrack, ...] = (
    SoundBedTrack(
        id="sb-morning-dew-1",
        title="Morning Dew and Warm Light",
        artist="Anuvritti Ensemble",
        license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        content_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        duration_seconds=180.0,
        tags=("gentle", "acoustic", "morning"),
        is_license_clean=True,
    ),
    SoundBedTrack(
        id="sb-quiet-piano-1",
        title="Quiet Steps on Wooden Floor",
        artist="Anuvritti Ensemble",
        license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        content_hash="ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
        duration_seconds=240.0,
        tags=("piano", "reflective", "warm"),
        is_license_clean=True,
    ),
    SoundBedTrack(
        id="sb-playful-acoustic-1",
        title="Little Bicycle Bell",
        artist="Anuvritti Ensemble",
        license="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        content_hash="4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce",
        duration_seconds=150.0,
        tags=("playful", "guitar", "sunlight"),
        is_license_clean=True,
    ),
    SoundBedTrack(
        id="sb-gentle-strings-1",
        title="Lullaby in November",
        artist="Anuvritti Ensemble",
        license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        content_hash="4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
        duration_seconds=210.0,
        tags=("strings", "calm", "evening"),
        is_license_clean=True,
    ),
)


@runtime_checkable
class SoundBedCatalogue(Protocol):
    """Port for discovering and verifying licence-clean audio bed tracks."""

    def get(self, track_id: str) -> Result[SoundBedTrack, DomainError]:
        """Fetch sound bed track by ID."""
        ...

    def list_tracks(self) -> tuple[SoundBedTrack, ...]:
        """List all approved licence-clean sound beds."""
        ...

    def verify_track(
        self, track_id: str, expected_hash: str | None = None
    ) -> Result[SoundBedTrack, DomainError]:
        """Verify track is present in catalogue, licence-clean, and matches hash."""
        ...


class StaticSoundBedCatalogue:
    """In-memory approved sound bed catalogue."""

    def __init__(self, tracks: tuple[SoundBedTrack, ...] = APPROVED_SOUND_BEDS) -> None:
        self._tracks = {t.id: t for t in tracks}

    def get(self, track_id: str) -> Result[SoundBedTrack, DomainError]:
        track = self._tracks.get(track_id)
        if track is None:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_NOT_FOUND,
                    f"Sound bed track {track_id!r} is not in the approved catalogue",
                    {"track_id": track_id},
                )
            )
        return Ok(track)

    def list_tracks(self) -> tuple[SoundBedTrack, ...]:
        return tuple(self._tracks.values())

    def verify_track(
        self, track_id: str, expected_hash: str | None = None
    ) -> Result[SoundBedTrack, DomainError]:
        track = self._tracks.get(track_id)
        if track is None:
            return Err(
                DomainError(
                    ErrorCode.MEDIA_NOT_FOUND,
                    f"Sound bed track {track_id!r} is not in the approved catalogue",
                    {"track_id": track_id},
                )
            )
        if not track.is_license_clean:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    f"Sound bed track {track_id!r} is not marked licence-clean",
                    {"track_id": track_id, "license": track.license},
                )
            )
        if expected_hash and track.content_hash != expected_hash:
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    (
                        f"Sound bed track {track_id!r} hash mismatch: "
                        f"{track.content_hash} != {expected_hash}"
                    ),
                    {
                        "track_id": track_id,
                        "expected": expected_hash,
                        "actual": track.content_hash,
                    },
                )
            )
        return Ok(track)


_DEFAULT_CATALOGUE = StaticSoundBedCatalogue()


def get_default_sound_catalogue() -> SoundBedCatalogue:
    return _DEFAULT_CATALOGUE
