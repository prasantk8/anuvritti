"""Whole archive exporter: produces sovereign, open family archives (PRD 45, PRD 24, PRD 44).

Generates a complete, self-contained directory containing:
1. `archive.json`: Root metadata, format version (1.0), family profile, children, members, counts.
2. `manifest.json`: Content-addressed SHA-256 integrity manifest for all files.
3. `sparks.json`: All captured Sparks with discrete provenance.
4. `moments.json`: Lived Moments with reflections and media references.
5. `voice_notes.json`: Voice recordings with transcripts and duration.
6. `little_things.json`: Childhood vocabulary and moments of wonder.
7. `lexicon.json`: The family's private terms.
8. `media/`: Decrypted plaintext media files (photos, audio notes).
9. `READER.html`: Standalone, single-file offline HTML viewer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anuvritti.application.ports import (
    FamilyRepository,
    LexiconRepository,
    LittleThingRepository,
    MediaStore,
    MomentRepository,
    SparkRepository,
    VoiceNoteRepository,
)
from anuvritti.application.privacy import spark_to_export
from anuvritti.domain.artifact import FamilyArtifact
from anuvritti.shared.clock import Clock, SystemClock
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import FamilyId, MediaId
from anuvritti.shared.result import Err, Ok, Result

__all__ = [
    "ARCHIVE_FORMAT_VERSION",
    "ExportArchiveUseCase",
    "FamilyArtifact",
    "WholeArchiveResult",
]

ARCHIVE_FORMAT_VERSION = "1.0"

_MIME_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/webp": ".webp",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "video/mp4": ".mp4",
}

_OFFLINE_READER_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anuvritti Family Archive</title>
  <style>
    :root {
      --bg: #faf8f5;
      --card-bg: #ffffff;
      --text: #1a1918;
      --text-muted: #6b6762;
      --saffron: #d97706;
      --border: #e7e5e4;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      max-width: 800px;
      margin: 0 auto;
      padding: 2rem 1rem;
      line-height: 1.5;
    }
    header { margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1rem; }
    h1 { margin: 0 0 0.5rem 0; font-size: 1.75rem; color: var(--text); }
    .meta { color: var(--text-muted); font-size: 0.9rem; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      margin-bottom: 1rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .card-title { font-weight: 600; font-size: 1.1rem; margin-bottom: 0.5rem; }
    .card-body { color: var(--text-muted); font-size: 0.95rem; }
    .pill {
      display: inline-block;
      padding: 0.2rem 0.5rem;
      background: #fef3c7;
      color: var(--saffron);
      border-radius: 4px;
      font-size: 0.8rem;
      font-weight: 500;
      margin-bottom: 0.5rem;
    }
    audio, img { max-width: 100%; border-radius: 4px; margin-top: 0.75rem; display: block; }
  </style>
</head>
<body>
  <header>
    <h1 id="family-name">Anuvritti Archive</h1>
    <div class="meta" id="archive-meta">Loading sovereign family archive...</div>
  </header>
  <main id="content">
    <p>Everything here happened. Nothing here was invented.</p>
  </main>
  <script>
    // Self-contained offline reader logic
    async function loadArchive() {
      try {
        const rootRes = await fetch('archive.json');
        if (!rootRes.ok) return;
        const root = await rootRes.json();
        document.getElementById('family-name').textContent = root.family.name;
        document.getElementById('archive-meta').textContent =
          `Exported: ${root.exported_at} • Sparks: ${root.counts.sparks}` +
          ` • Moments: ${root.counts.moments}`;

        const sparksRes = await fetch('sparks.json');
        if (sparksRes.ok) {
          const sparks = await sparksRes.json();
          const container = document.getElementById('content');
          container.innerHTML = '';
          for (const s of sparks) {
            const el = document.createElement('div');
            el.className = 'card';
            el.innerHTML = `
              <span class="pill">${s.category ? s.category.value : 'MEMORY'}</span>
              <div class="card-title">${s.title}</div>
              <div class="card-body">${s.note || ''}</div>
              ${s.why && s.why.text ? `<p><em>Why: “${s.why.text}”</em></p>` : ''}
            `;
            container.appendChild(el);
          }
        }
      } catch (e) {
        console.error('Offline reader loaded statically');
      }
    }
    loadArchive();
  </script>
</body>
</html>
"""


@dataclass(frozen=True, slots=True)
class WholeArchiveResult:
    """The outcome of a whole archive export."""

    destination: Path
    file_count: int
    total_bytes: int
    manifest_path: Path
    root_metadata_path: Path


class ExportArchiveUseCase:
    """Produces a whole, open, self-contained family archive directory."""

    def __init__(
        self,
        families: FamilyRepository,
        sparks: SparkRepository,
        moments: MomentRepository,
        voice_notes: VoiceNoteRepository,
        little_things: LittleThingRepository,
        lexicons: LexiconRepository,
        media: MediaStore,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._families = families
        self._sparks = sparks
        self._moments = moments
        self._voice_notes = voice_notes
        self._little_things = little_things
        self._lexicons = lexicons
        self._media = media
        self._clock = clock or SystemClock()

    def execute(
        self,
        family_id: FamilyId,
        *,
        destination_dir: Path,
    ) -> Result[WholeArchiveResult, DomainError]:
        # 1. Fetch Family
        family_res = self._families.get(family_id)
        if family_res.is_err():
            return Err(family_res.unwrap_err())
        family = family_res.unwrap()

        # 2. Check Destination
        if destination_dir.exists() and any(destination_dir.iterdir()):
            return Err(
                DomainError(
                    ErrorCode.CONFLICT,
                    f"destination directory '{destination_dir}' already exists and is not empty",
                    {"destination": str(destination_dir)},
                )
            )
        destination_dir.mkdir(parents=True, exist_ok=True)
        media_dir = destination_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        films_dir = destination_dir / "films"
        films_dir.mkdir(parents=True, exist_ok=True)

        now = self._clock.now()

        # 3. Retrieve all domain records
        sparks_list = self._sparks.list_for_family(family_id).unwrap_or(())
        moments_list = self._moments.list_for_family(family_id).unwrap_or(())
        voice_list = self._voice_notes.list_for_family(family_id).unwrap_or(())
        little_things_list = self._little_things.list_for_family(family_id).unwrap_or(())
        lexicon_res = self._lexicons.load(family_id)
        lexicon_entries = lexicon_res.unwrap().entries.items() if lexicon_res.is_ok() else ()

        # 4. Serialize JSON data files
        sparks_data = [
            (s.to_dict() if hasattr(s, "to_dict") else spark_to_export(s)) for s in sparks_list
        ]
        (destination_dir / "sparks.json").write_text(
            json.dumps(sparks_data, indent=2, default=str), encoding="utf-8"
        )

        moments_data = [
            (
                m.to_dict()
                if hasattr(m, "to_dict")
                else {
                    "id": str(m.id),
                    "spark_id": str(m.spark_id),
                    "happened_on": m.happened_on.isoformat(),
                    "reflection": m.reflection,
                    "photo_media_id": str(m.photo_media_id) if m.photo_media_id else None,
                    "audio_media_id": str(m.audio_media_id) if m.audio_media_id else None,
                    "created_by": str(m.created_by),
                    "created_at": m.created_at.isoformat(),
                }
            )
            for m in moments_list
        ]
        (destination_dir / "moments.json").write_text(
            json.dumps(moments_data, indent=2, default=str), encoding="utf-8"
        )

        voice_data = [
            (
                v.to_dict()
                if hasattr(v, "to_dict")
                else {
                    "media_id": str(v.media_id),
                    "author_id": str(v.author_id),
                    "duration_seconds": v.duration_seconds,
                    "recorded_at": v.recorded_at.isoformat(),
                    "transcript": v.transcript.to_dict() if v.transcript else None,
                }
            )
            for v in voice_list
        ]
        (destination_dir / "voice_notes.json").write_text(
            json.dumps(voice_data, indent=2, default=str), encoding="utf-8"
        )

        little_data = [
            (
                lt.to_dict()
                if hasattr(lt, "to_dict")
                else {
                    "id": str(lt.id),
                    "family_id": str(lt.family_id),
                    "author_id": str(lt.author_id),
                    "subject_child_id": (str(lt.subject_child_id) if lt.subject_child_id else None),
                    "text": lt.text,
                    "audio_media_id": lt.audio_media_id,
                    "created_at": lt.created_at.isoformat(),
                }
            )
            for lt in little_things_list
        ]
        (destination_dir / "little_things.json").write_text(
            json.dumps(little_data, indent=2, default=str), encoding="utf-8"
        )

        lexicon_data = [
            {
                "field": field.value if hasattr(field, "value") else str(field),
                "term": term,
                "means": means,
                "times": evidence.times,
                "last_at": evidence.last_at.isoformat(),
            }
            for (field, term, means), evidence in lexicon_entries
        ]
        (destination_dir / "lexicon.json").write_text(
            json.dumps(lexicon_data, indent=2, default=str), encoding="utf-8"
        )

        # 5. Export Plaintext Media Files
        exported_media_ids: set[str] = set()
        for spark in sparks_list:
            if spark.source.media_id:
                exported_media_ids.add(str(spark.source.media_id))
            if spark.why and spark.why.voice_media_id:
                exported_media_ids.add(str(spark.why.voice_media_id))

        for moment in moments_list:
            if moment.photo_media_id:
                exported_media_ids.add(str(moment.photo_media_id))
            if moment.audio_media_id:
                exported_media_ids.add(str(moment.audio_media_id))

        for voice in voice_list:
            exported_media_ids.add(str(voice.media_id))

        for lt in little_things_list:
            if lt.audio_media_id:
                exported_media_ids.add(str(lt.audio_media_id))

        media_count = 0
        for mid_str in sorted(exported_media_ids):
            mid = MediaId(mid_str)
            data_res = self._media.get(mid)
            desc_res = self._media.describe(mid)
            if data_res.is_ok():
                data_bytes = data_res.unwrap()
                mime = (
                    desc_res.unwrap().mime_type if desc_res.is_ok() else "application/octet-stream"
                )
                ext = _MIME_EXTENSIONS.get(mime, ".bin")
                target_path = media_dir / f"{mid_str}{ext}"
                target_path.write_bytes(data_bytes)
                media_count += 1

        # 6. Write Root Metadata (archive.json)
        root_data: dict[str, Any] = {
            "format_version": ARCHIVE_FORMAT_VERSION,
            "archive_id": f"arc-{family_id}-{now.strftime('%Y%m%d%H%M%S')}",
            "exported_at": now.isoformat(),
            "family": {
                "id": str(family.id),
                "name": family.name,
                "created_at": family.created_at.isoformat(),
            },
            "children": [
                {
                    "id": str(c.id),
                    "display_name": c.display_name,
                    "date_of_birth": c.date_of_birth.isoformat(),
                }
                for c in family.children
            ],
            "members": [
                {
                    "id": str(m.id),
                    "display_name": m.display_name,
                    "role": m.role.value,
                }
                for m in family.members
            ],
            "counts": {
                "sparks": len(sparks_list),
                "moments": len(moments_list),
                "voice_notes": len(voice_list),
                "little_things": len(little_things_list),
                "lexicon_terms": len(lexicon_data),
                "media_files": media_count,
            },
        }
        root_path = destination_dir / "archive.json"
        root_path.write_text(json.dumps(root_data, indent=2, default=str), encoding="utf-8")

        # 7. Write Offline Reader
        reader_path = destination_dir / "READER.html"
        reader_path.write_text(_OFFLINE_READER_TEMPLATE, encoding="utf-8")

        # 8. Compute Manifest with SHA-256 for all files
        manifest_files: list[dict[str, Any]] = []
        total_bytes = 0

        for file_path in sorted(destination_dir.rglob("*")):
            if file_path.is_file() and file_path.name != "manifest.json":
                data_bytes = file_path.read_bytes()
                sha256_hash = hashlib.sha256(data_bytes).hexdigest()
                rel_path = file_path.relative_to(destination_dir).as_posix()
                mime = "application/json" if file_path.suffix == ".json" else "text/html"
                if "media" in rel_path:
                    # Invert lookup
                    for m_mime, m_ext in _MIME_EXTENSIONS.items():
                        if file_path.suffix == m_ext:
                            mime = m_mime
                            break

                manifest_files.append(
                    {
                        "relative_path": rel_path,
                        "byte_size": len(data_bytes),
                        "mime_type": mime,
                        "sha256": sha256_hash,
                    }
                )
                total_bytes += len(data_bytes)

        manifest_data = {
            "algorithm": "SHA-256",
            "generated_at": now.isoformat(),
            "files": manifest_files,
        }
        manifest_path = destination_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2, default=str), encoding="utf-8")

        return Ok(
            WholeArchiveResult(
                destination=destination_dir,
                file_count=len(manifest_files) + 1,
                total_bytes=total_bytes,
                manifest_path=manifest_path,
                root_metadata_path=root_path,
            )
        )
