"""Render an explicitly fictional teaser through the real film pipeline.

The seed lives under the requested workspace and never enters source control. It is demo
material, not a family archive: its purpose is to make the destination inspectable before a
family has accumulated a year of private material.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from filmkit.process import run

from anuvritti.adapters.film.export import FilesystemFilmExporter
from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.adapters.film.render import ChromiumFfmpegRenderer
from anuvritti.adapters.media.filesystem import EncryptedFilesystemMediaStore
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import (
    SqliteFamilyRepository,
    SqliteLittleThingRepository,
    SqliteMediaCatalogue,
    SqliteMomentRepository,
    SqliteSparkRepository,
    SqliteVoiceNoteRepository,
)
from anuvritti.application.film import CompileFilmUseCase, ComposeFilmCommand, ComposeFilmUseCase
from anuvritti.application.ports import RenderedFilm
from anuvritti.application.provenance import VerifyProvenanceUseCase
from anuvritti.config.settings import DEFAULT_ALLOWED_MEDIA_TYPES
from anuvritti.domain.family import ChildProfile, Family, Member
from anuvritti.domain.moment import Moment
from anuvritti.domain.spark import Spark
from anuvritti.domain.values import MemberRole, SourceRef
from anuvritti.domain.voice import VoiceNote
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import (
    ChildId,
    FamilyId,
    MemberId,
    MomentId,
    SequentialIdGenerator,
    SparkId,
)
from anuvritti.shared.result import Err, Result

_FAMILY = FamilyId("teaser-family")
_PARENT = MemberId("teaser-parent")
_CHILD = ChildId("teaser-child")
_NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
_SCENES = (
    ("The red umbrella", "Rain became the whole afternoon."),
    ("A kitchen constellation", "Flour on every surface, including us."),
    ("The long way home", "We stopped for every interesting stone."),
    ("A cardboard city", "By supper it had a train station."),
    ("The first brave jump", "You checked that I was watching."),
    ("Blue hour", "Nobody wanted to be the first to go inside."),
)
_COLOURS = ("5c6858", "c98256", "526477", "8b735c", "756477", "3f5f62")


def seed_teaser(directory: Path) -> tuple[tuple[Path, Path], ...]:
    """Create twelve deterministic media files, or use the complete seed already there."""
    directory.mkdir(parents=True, exist_ok=True)
    pairs = tuple(
        (directory / f"{index:02d}.png", directory / f"{index:02d}.wav") for index in range(1, 7)
    )
    existing = [path for pair in pairs for path in pair if path.exists()]
    if existing and len(existing) != 12:
        raise ValueError("the teaser seed is incomplete; expected six PNG and six WAV files")
    if len(existing) == 12:
        return pairs

    for index, ((picture, recording), colour) in enumerate(zip(pairs, _COLOURS, strict=True)):
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x{colour}:s=960x540,drawgrid=w=96:h=54:t=2:c=white@0.12",
                "-frames:v",
                "1",
                str(picture),
            ],
            timeout=30,
            check=True,
        )
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={180 + index * 23}:sample_rate=48000:duration=0.6",
                "-c:a",
                "pcm_s16le",
                str(recording),
            ],
            timeout=30,
            check=True,
        )
    return pairs


def render_teaser(
    *,
    destination: Path,
    workspace: Path,
    seed_directory: Path,
    receipt: Path,
    provenance_receipt: Path,
) -> Result[RenderedFilm, DomainError]:
    """Seed, compile, export and render the teaser with production adapters."""
    try:
        media_pairs = seed_teaser(seed_directory)
        workspace.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="teaser-", dir=workspace) as temporary:
            root = Path(temporary)
            connection = connect(str(root / "archive.db"))
            migrate(connection)
            try:
                families = SqliteFamilyRepository(connection)
                sparks = SqliteSparkRepository(connection)
                moments = SqliteMomentRepository(connection)
                voice_notes = SqliteVoiceNoteRepository(connection)
                little_things = SqliteLittleThingRepository(connection)
                media = EncryptedFilesystemMediaStore(
                    root=root / "vault",
                    catalogue=SqliteMediaCatalogue(connection),
                    ids=SequentialIdGenerator("teaser-media"),
                    encryption_key=Fernet.generate_key().decode(),
                    max_bytes=8 * 1024 * 1024,
                    allowed_mime_types=DEFAULT_ALLOWED_MEDIA_TYPES,
                )
                families.save(
                    Family(
                        id=_FAMILY,
                        name="A year, held close",
                        members=(Member(_PARENT, "A parent", MemberRole.PARENT),),
                        children=(
                            ChildProfile(
                                _CHILD, MemberId("teaser-child-member"), "Aarav", date(2020, 5, 1)
                            ),
                        ),
                        created_at=_NOW,
                    )
                ).unwrap()
                for index, ((picture, recording), (title, reflection)) in enumerate(
                    zip(media_pairs, _SCENES, strict=True), start=1
                ):
                    photo = media.put(
                        _FAMILY, content=picture.read_bytes(), mime_type="image/png", at=_NOW
                    ).unwrap()
                    audio = media.put(
                        _FAMILY, content=recording.read_bytes(), mime_type="audio/wav", at=_NOW
                    ).unwrap()
                    voice_notes.save(
                        VoiceNote.kept(
                            media_id=audio.id,
                            family_id=_FAMILY,
                            author_id=_PARENT,
                            duration_seconds=0.6,
                            at=_NOW,
                        ).unwrap()
                    ).unwrap()
                    happened = date(2026, index, min(4 + index * 3, 28))
                    at = datetime.combine(happened, datetime.min.time(), tzinfo=UTC)
                    spark = Spark.capture(
                        spark_id=SparkId(f"teaser-spark-{index}"),
                        family_id=_FAMILY,
                        owner_id=_PARENT,
                        source=SourceRef.from_text(title),
                        at=at,
                        subject_child_id=_CHILD,
                    )
                    sparks.save(spark).unwrap()
                    moments.save(
                        Moment.create(
                            moment_id=MomentId(f"teaser-moment-{index}"),
                            family_id=_FAMILY,
                            spark_id=spark.id,
                            created_by=_PARENT,
                            spark_captured_at=at,
                            at=at,
                            happened_on=happened,
                            reflection=reflection,
                            photo_media_id=str(photo.id),
                            audio_media_id=str(audio.id),
                        ).unwrap()
                    ).unwrap()

                compose = ComposeFilmUseCase(
                    families=families,
                    sparks=sparks,
                    moments=moments,
                    voice_notes=voice_notes,
                    media=media,
                    ids=SequentialIdGenerator("teaser-film"),
                )
                verify = VerifyProvenanceUseCase(
                    sparks=sparks,
                    moments=moments,
                    voice_notes=voice_notes,
                    little_things=little_things,
                    media=media,
                    clock=FrozenClock(_NOW),
                )
                package = (
                    CompileFilmUseCase(
                        compose=compose, verify=verify, compiler=FilmkitFilmCompiler()
                    )
                    .execute(
                        ComposeFilmCommand(
                            family_id=_FAMILY,
                            actor_id=_PARENT,
                            child_id=_CHILD,
                            title="Aarav, this year",
                        )
                    )
                    .unwrap()
                )
                exported = (
                    FilesystemFilmExporter(media).export(package, into=root / "export").unwrap()
                )
                shutil.copy2(exported.film_path, receipt)
                shutil.copy2(exported.provenance_path, provenance_receipt)
                return ChromiumFfmpegRenderer(workspace=workspace / "render").render(
                    exported.directory, destination=destination
                )
            finally:
                connection.close()
    except Exception as exc:
        return Err(
            DomainError(
                ErrorCode.FILM_NOT_COMPILABLE,
                "the teaser could not be made from its local demo seed",
                {"reason": str(exc)},
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the local, explicitly fictional teaser")
    parser.add_argument("--output", type=Path, default=Path("var/film/teaser.mp4"))
    parser.add_argument("--workspace", type=Path, default=Path("var/teaser/work"))
    parser.add_argument("--seed", type=Path, default=Path("var/teaser/media"))
    parser.add_argument("--receipt", type=Path, default=Path("var/film/teaser-film.json"))
    parser.add_argument("--provenance", type=Path, default=Path("var/film/teaser-provenance.json"))
    arguments = parser.parse_args()
    result = render_teaser(
        destination=arguments.output,
        workspace=arguments.workspace,
        seed_directory=arguments.seed,
        receipt=arguments.receipt,
        provenance_receipt=arguments.provenance,
    )
    if result.is_err():
        error = result.unwrap_err()
        print(error.message)
        print(error.details["reason"])
        return 1
    film = result.unwrap()
    print(f"teaser {film.path} ({film.duration_seconds:.3f}s, {len(film.frames)} scenes)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by `make teaser`
    raise SystemExit(main())
