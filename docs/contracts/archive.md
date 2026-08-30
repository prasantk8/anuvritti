# Family Archive Format Specification (v1.0)

This document is the normative contract for the Anuvritti Family Archive (PRD 45, PRD 52, PRD 37).
An archive exported under this specification is self-contained, human-readable, and complete enough
that a complete reader or migration tool can be built from this specification alone without this codebase.

---

## 1. Top-Level Directory Layout

A valid Anuvritti archive folder (or uncompressed `.tar` / `.zip` export) must have the following layout:

```
archive-root/
├── archive.json          # Root metadata, format version, family profile, and checksums
├── manifest.json         # Cryptographic manifest of every file in the archive (SHA-256)
├── sparks.json           # All captured sparks with discrete provenance
├── moments.json          # All lived moments with reflections and media references
├── voice_notes.json      # Voice notes with duration and transcripts
├── little_things.json    # Vocabulary, quotes, and childhood little things
├── lexicon.json          # Family-specific private lexicon terms
├── films/                # Compiled films, specs, and receipts
│   └── <film_id>/
│       ├── spec.json
│       ├── provenance.json
│       ├── cues.vtt
│       └── film.mp4      # Optional rendered output
├── media/                # Raw photographs, audio recordings, and videos
│   ├── photo-1.jpg
│   └── voice-1.wav
└── READER.html           # Standalone single-file offline archive reader
```

---

## 2. File Specifications

### 2.1 `archive.json` (Root Metadata)

```json
{
  "format_version": "1.0",
  "archive_id": "arc-2026-001",
  "exported_at": "2026-08-31T00:00:00Z",
  "family": {
    "id": "fam-1",
    "name": "The Singh Family",
    "created_at": "2026-01-01T00:00:00Z"
  },
  "children": [
    {
      "id": "child-1",
      "display_name": "Leo",
      "date_of_birth": "2024-05-12"
    }
  ],
  "members": [
    {
      "id": "mem-1",
      "display_name": "Papa",
      "role": "PARENT"
    }
  ],
  "counts": {
    "sparks": 42,
    "moments": 18,
    "voice_notes": 12,
    "little_things": 7,
    "films": 2,
    "media_files": 35,
    "total_bytes": 104857600
  }
}
```

### 2.2 `manifest.json` (Integrity & Fixity)

Every file in the archive (including JSON files, media files, and films) is listed in `manifest.json`.

```json
{
  "algorithm": "SHA-256",
  "generated_at": "2026-08-31T00:00:00Z",
  "files": [
    {
      "relative_path": "sparks.json",
      "byte_size": 15420,
      "mime_type": "application/json",
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    },
    {
      "relative_path": "media/photo-1.jpg",
      "byte_size": 2405912,
      "mime_type": "image/jpeg",
      "sha256": "77b8b40aa548aa2a6113b28b7e285d8e4823297a783307bb2838383838383838"
    }
  ]
}
```

### 2.3 `sparks.json` (Captured Memories)

```json
[
  {
    "id": "spark-101",
    "owner_id": "mem-1",
    "subject_child_id": "child-1",
    "title": "Taking first steps on the living room rug",
    "note": "Walking towards mama with big smiles",
    "source": {
      "kind": "MANUAL",
      "url": null,
      "creator": null,
      "title": null,
      "text": null,
      "media_id": null
    },
    "intent": {
      "value": "DO",
      "source": "PARENT",
      "confidence": 1.0,
      "overridden": false
    },
    "category": {
      "value": "MOVEMENT",
      "source": "PARENT",
      "confidence": 1.0,
      "overridden": false
    },
    "age_range": {
      "min_years": 1,
      "max_years": 2,
      "source": "PARENT",
      "confidence": 1.0,
      "overridden": false
    },
    "why": {
      "text": "He looked so proud of himself",
      "voice_media_id": "media-voice-why-1",
      "recorded_at": "2026-06-01T14:30:00Z"
    },
    "status": "LIVED",
    "created_at": "2026-06-01T14:00:00Z",
    "updated_at": "2026-06-01T14:30:00Z"
  }
]
```

### 2.4 `moments.json` (Lived Moments)

```json
[
  {
    "id": "moment-201",
    "spark_id": "spark-101",
    "happened_on": "2026-06-01",
    "reflection": "A beautiful sunny afternoon.",
    "photo_media_id": "media-photo-1",
    "audio_media_id": "media-voice-1",
    "created_by": "mem-1",
    "created_at": "2026-06-01T15:00:00Z"
  }
]
```

### 2.5 `voice_notes.json`

```json
[
  {
    "media_id": "media-voice-1",
    "author_id": "mem-1",
    "duration_seconds": 4.5,
    "recorded_at": "2026-06-01T15:00:00Z",
    "transcript": {
      "text": "Look at him walking!",
      "source": "ON_DEVICE_WHISPER",
      "confidence": 0.98,
      "engine": "whisper.cpp-small",
      "made_at": "2026-06-01T15:00:05Z"
    }
  }
]
```

### 2.6 `little_things.json`

```json
[
  {
    "id": "lt-1",
    "child_id": "child-1",
    "kind": "WORD",
    "text": "Dadaa",
    "context": "First said while pointing at shoes",
    "heard_on": "2026-04-10",
    "audio_media_id": "media-voice-dadaa",
    "recorded_by": "mem-1",
    "created_at": "2026-04-10T10:00:00Z"
  }
]
```

### 2.7 `lexicon.json`

```json
[
  {
    "field": "category",
    "term": "choo-choo",
    "means": "TRAIN",
    "times": 5,
    "last_at": "2026-05-01T08:00:00Z"
  }
]
```

---

## 3. Guarantees & Non-Functional Invariants

1. **No External Network Dependencies**: Reading this archive requires no internet connection, external API, license check, or DNS lookup.
2. **Bit-for-Bit Fixity**: Re-running SHA-256 verification over all items listed in `manifest.json` must match exactly 100% of digests.
3. **Discrete Provenance**: All machine-inferred attributes (transcripts, categories, intents) carry explicit source, engine, and confidence values.
4. **Permanent Sovereign Retention**: The archive represents a complete snapshot of all sovereign family data.
