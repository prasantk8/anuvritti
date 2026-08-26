"""Writing out the thing that travels: the film, its files, and its receipts (PRD 34, 47).

Everything upstream of here is careful never to hold a byte. The compiler does arithmetic,
the domain plans scenes, the ports refuse to describe a codec. This module is the one place
that copies a family's recordings out of the encrypted store and lays them down as ordinary
files, because at some point a machine with a browser on it has to be able to open them.

That makes this a small module with an uncomfortable job, so it does three things:

**It writes `provenance.json` beside the film, always.** Not as an option, not on a flag. The
package cannot exist without a clean ledger, and the ledger travels with what it vouches for
- an artifact folder found in fifteen years should answer "where did this come from" without
needing this codebase to still exist.

**It refuses a directory that already has something in it.** Two films' media in one folder
is how a photograph ends up in a film it was never cited by.

**It checks the bytes on the way out.** The store re-hashes on read; this re-hashes against
the hash the *bundle* recorded when the film was composed. Those are two different questions
- "are these the bytes we stored" and "are these the bytes this film was measured against" -
and the second one is the one a renderer's cache depends on.

What lands on disk is plaintext: real photographs and real recordings of a child, outside the
vault that was protecting them. The export directory is created 0700 and the caller is
expected to delete it when the film is drawn. That is a weaker guarantee than encryption at
rest, and it is stated here rather than hidden, because the alternative - shipping the key to
the render machine - is worse.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from anuvritti.application.ports import MediaStore
from anuvritti.domain.film import PROVENANCE_FILENAME, FilmPackage
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import MediaId
from anuvritti.shared.result import Err, Ok, Result

FILM_FILENAME = "film.json"
MEDIA_DIRECTORY = "media"

#: Deliberately a fixed table rather than `mimetypes`, whose answers depend on the machine's
#: own configuration. An export must lay down the same filenames on every machine, because a
#: renderer's cache is keyed on them.
_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
}
_UNKNOWN_EXTENSION = ".bin"


@dataclass(frozen=True, slots=True)
class FilmExport:
    """Where everything landed. Paths, so a caller can hand the folder somewhere and delete it."""

    directory: Path
    film_path: Path
    provenance_path: Path
    media_paths: tuple[Path, ...]
    byte_size: int


class FilesystemFilmExporter:
    """Lays a `FilmPackage` down as a folder a renderer can be pointed at."""

    __slots__ = ("_media",)

    def __init__(self, media: MediaStore) -> None:
        self._media = media

    def export(self, package: FilmPackage, *, into: Path) -> Result[FilmExport, DomainError]:
        if into.exists() and any(into.iterdir()):
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    "that folder already holds something, and an export will not mix two films",
                    {"directory": str(into)},
                )
            )

        media_dir = into / MEDIA_DIRECTORY
        media_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

        written: list[Path] = []
        total = 0
        for item in package.bundle.items:
            content = self._media.get(item.id)
            if content.is_err():
                return Err(content.unwrap_err())
            body = content.unwrap()

            if hashlib.sha256(body).hexdigest() != item.content_hash:
                return Err(_altered(item.id))

            path = media_dir / f"{item.id}{_EXTENSIONS.get(item.mime_type, _UNKNOWN_EXTENSION)}"
            path.write_bytes(body)
            written.append(path)
            total += len(body)

        film_path = into / FILM_FILENAME
        film_path.write_text(
            json.dumps(
                {"film": package.film.to_dict(), "bundle": package.bundle.to_dict()},
                indent=2,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        provenance_path = into / PROVENANCE_FILENAME
        provenance_path.write_text(
            json.dumps(package.provenance.to_dict(), indent=2, sort_keys=False),
            encoding="utf-8",
        )

        return Ok(
            FilmExport(
                directory=into,
                film_path=film_path,
                provenance_path=provenance_path,
                media_paths=tuple(written),
                byte_size=total,
            )
        )


def _altered(media_id: MediaId) -> DomainError:
    return DomainError(
        ErrorCode.CONFLICT,
        f"media {media_id} is not the file this film was measured against, and will not travel",
        {"media_id": str(media_id)},
    )
