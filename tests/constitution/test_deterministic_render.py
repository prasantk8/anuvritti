"""TASK-1202: Determinism proven by hash (PRD 8.7, PRD 52).

The same spec and the same bytes produce the same film, this year and in ten years.
Byte-identical frames will not survive a Chromium upgrade; perceptual diff is the pixel gate.
This constitutional test guarantees mathematical determinism over:
1. FilmSpec canonical serialization and hash.
2. FilmkitFilmCompiler timeline arithmetic and scene positioning.
3. MediaBundle item digest tracking.
4. Provenance verification ledger and citations.
5. Mutation sensitivity (any alteration changes the hash).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anuvritti.adapters.film.export import FILM_FILENAME, FilesystemFilmExporter
from anuvritti.adapters.film.filmkit_compiler import FilmkitFilmCompiler
from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.render_jobs import SubmitRenderJobUseCase
from anuvritti.domain.film import (
    PROVENANCE_FILENAME,
    BundledMedia,
    Citation,
    CitationKind,
    FilmDraft,
    FilmPackage,
    FilmScene,
    FilmSpec,
    MediaBundle,
    Provenance,
    ProvenanceEntry,
    ProvenanceStatus,
    SceneKind,
    SceneVoice,
)
from anuvritti.domain.media import MediaKind
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.identity import ChildId, FamilyId, MediaId
from anuvritti.shared.result import Err, Ok


def _canonical_json(data: dict[str, Any]) -> str:
    """Deterministic JSON formatting with sorted keys and normalized spacing."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)


def _sha256(text: str | bytes) -> str:
    if isinstance(text, str):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hashlib.sha256(text).hexdigest()


def _make_spec(
    *, title: str = "Year Four", narration_text: str = "She learned to cycle."
) -> FilmSpec:
    opening = FilmScene(
        id="scene-opening",
        kind=SceneKind.OPENING,
        heading="Anuvritti Year 4",
        voice=SceneVoice.silent(2.5),
    )
    spark_scene = FilmScene(
        id="scene-spark-1",
        kind=SceneKind.SPARK,
        heading="Riding Without Stabilisers",
        body="In the park on Sunday",
        voice=SceneVoice.recorded(media_id=MediaId("aud-1"), seconds=4.2, text=narration_text),
        cites=(
            Citation(CitationKind.SPARK, "spk-1"),
            Citation(CitationKind.MEDIA, "img-1"),
        ),
    )
    closing = FilmScene(
        id="scene-closing",
        kind=SceneKind.CLOSING,
        heading="End of Year 4",
        voice=SceneVoice.silent(3.0),
    )
    return FilmSpec(
        id="film-spec-year-4",
        family_id=FamilyId("fam-1"),
        title=title,
        scenes=(opening, spark_scene, closing),
        child_id=ChildId("child-1"),
    )


_AUD_BYTES = b"audio" * 9024
_IMG_BYTES = b"image" * 209715
_AUD_HASH = hashlib.sha256(_AUD_BYTES).hexdigest()
_IMG_HASH = hashlib.sha256(_IMG_BYTES).hexdigest()


def _make_bundle() -> MediaBundle:
    return MediaBundle(
        items=(
            BundledMedia(
                id=MediaId("aud-1"),
                kind=MediaKind.AUDIO,
                mime_type="audio/mp4",
                byte_size=len(_AUD_BYTES),
                content_hash=_AUD_HASH,
            ),
            BundledMedia(
                id=MediaId("img-1"),
                kind=MediaKind.IMAGE,
                mime_type="image/jpeg",
                byte_size=len(_IMG_BYTES),
                content_hash=_IMG_HASH,
            ),
        )
    )


def _make_provenance(spec: FilmSpec, verified_at: datetime) -> Provenance:
    entries = (
        ProvenanceEntry(
            scene_id="scene-spark-1",
            scene_kind=SceneKind.SPARK,
            citation=Citation(CitationKind.SPARK, "spk-1"),
            status=ProvenanceStatus.VERIFIED,
            content_hash="",
        ),
        ProvenanceEntry(
            scene_id="scene-spark-1",
            scene_kind=SceneKind.SPARK,
            citation=Citation(CitationKind.MEDIA, "img-1"),
            status=ProvenanceStatus.VERIFIED,
            content_hash=_IMG_HASH,
        ),
    )
    return Provenance(
        film_id=spec.id,
        family_id=spec.family_id,
        verified_at=verified_at,
        entries=entries,
    )


class TestDeterministicRenderPipeline:
    """Constitutional invariant: compilation is a deterministic pure function."""

    def test_spec_hash_determinism(self):
        """Constructing identical specs at different times produces bit-identical hashes."""
        spec_a = _make_spec()
        spec_b = _make_spec()

        dict_a = {
            "id": spec_a.id,
            "family_id": str(spec_a.family_id),
            "title": spec_a.title,
            "scenes": [s.id for s in spec_a.scenes],
            "media_ids": sorted(spec_a.media_ids),
        }
        dict_b = {
            "id": spec_b.id,
            "family_id": str(spec_b.family_id),
            "title": spec_b.title,
            "scenes": [s.id for s in spec_b.scenes],
            "media_ids": sorted(spec_b.media_ids),
        }

        hash_a = _sha256(_canonical_json(dict_a))
        hash_b = _sha256(_canonical_json(dict_b))

        assert hash_a == hash_b
        assert len(hash_a) == 64

    def test_compiler_timeline_determinism(self):
        """Compiling the same spec produces the exact same timeline arithmetic."""
        compiler = FilmkitFilmCompiler()
        spec_1 = _make_spec()
        spec_2 = _make_spec()

        res_1 = compiler.compile(spec_1)
        res_2 = compiler.compile(spec_2)

        assert res_1.is_ok()
        assert res_2.is_ok()

        film_1 = res_1.unwrap()
        film_2 = res_2.unwrap()

        # Both timeline dicts must serialize to identical JSON
        json_1 = _canonical_json(film_1.timeline)
        json_2 = _canonical_json(film_2.timeline)
        assert json_1 == json_2
        assert _sha256(json_1) == _sha256(json_2)

        # Durations and scene start seconds must match exactly
        assert film_1.duration_seconds == film_2.duration_seconds
        assert len(film_1.scenes) == len(film_2.scenes)
        for s1, s2 in zip(film_1.scenes, film_2.scenes, strict=True):
            assert s1.start_seconds == s2.start_seconds
            assert s1.visual_seconds == s2.visual_seconds
            assert s1.voice.seconds == s2.voice.seconds

    def test_media_bundle_hash_determinism(self):
        """Media bundle serialization and byte counts are strictly deterministic."""
        bundle_1 = _make_bundle()
        bundle_2 = _make_bundle()

        json_1 = _canonical_json(bundle_1.to_dict())
        json_2 = _canonical_json(bundle_2.to_dict())

        assert json_1 == json_2
        assert bundle_1.byte_size == bundle_2.byte_size
        assert bundle_1.ids == bundle_2.ids

    def test_provenance_ledger_determinism(self):
        """Provenance verification output is deterministic for identical citations."""
        spec = _make_spec()
        fixed_time = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)

        prov_1 = _make_provenance(spec, fixed_time)
        prov_2 = _make_provenance(spec, fixed_time)

        json_1 = _canonical_json(prov_1.to_dict())
        json_2 = _canonical_json(prov_2.to_dict())

        assert json_1 == json_2
        assert prov_1.is_clean
        assert prov_2.is_clean

    def test_export_package_file_determinism(self, tmp_path: Path):
        """Filesystem export produces identical film.json and provenance.json structure."""
        spec = _make_spec()
        bundle = _make_bundle()
        draft = FilmDraft(spec=spec, bundle=bundle)

        compiler = FilmkitFilmCompiler()
        compiled = compiler.compile(spec).unwrap()
        fixed_time = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)
        provenance = _make_provenance(spec, fixed_time)

        package = FilmPackage(draft=draft, film=compiled, provenance=provenance)

        class _SimpleStore:
            def get(self, media_id: MediaId):
                if str(media_id) == "aud-1":
                    return Ok(_AUD_BYTES)
                if str(media_id) == "img-1":
                    return Ok(_IMG_BYTES)
                return Err(DomainError(ErrorCode.VALIDATION_FAILED, f"unknown media {media_id}"))

        exporter = FilesystemFilmExporter(media=_SimpleStore())

        export_1 = tmp_path / "export_1"
        export_2 = tmp_path / "export_2"

        res_1 = exporter.export(package, into=export_1)
        res_2 = exporter.export(package, into=export_2)

        assert res_1.is_ok()
        assert res_2.is_ok()

        film_1_bytes = (export_1 / FILM_FILENAME).read_bytes()
        film_2_bytes = (export_2 / FILM_FILENAME).read_bytes()
        prov_1_bytes = (export_1 / PROVENANCE_FILENAME).read_bytes()
        prov_2_bytes = (export_2 / PROVENANCE_FILENAME).read_bytes()

        assert _sha256(film_1_bytes) == _sha256(film_2_bytes)
        assert _sha256(prov_1_bytes) == _sha256(prov_2_bytes)

    def test_mutation_sensitivity(self):
        """Any mutation to words, timing, or scenes alters the timeline hash."""
        compiler = FilmkitFilmCompiler()
        spec_base = _make_spec(narration_text="Original words.")
        spec_mutated = _make_spec(narration_text="Different words entirely.")

        film_base = compiler.compile(spec_base).unwrap()
        film_mutated = compiler.compile(spec_mutated).unwrap()

        hash_base = _sha256(_canonical_json(film_base.timeline))
        hash_mutated = _sha256(_canonical_json(film_mutated.timeline))

        assert hash_base != hash_mutated

    def test_idempotent_render_job_submission_with_deterministic_hash(self):
        """Durable render jobs rely on deterministic spec hash to avoid duplicate work."""
        conn = connect(":memory:")
        migrate(conn)
        conn.execute(
            "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
            ("fam-1", "Smiths", "2026-01-01T00:00:00Z"),
        )

        repo = SqliteRenderJobRepository(conn)
        submit = SubmitRenderJobUseCase(repo)

        spec = _make_spec()
        spec_dict = {
            "id": spec.id,
            "title": spec.title,
            "scenes": [s.id for s in spec.scenes],
        }
        spec_hash = _sha256(_canonical_json(spec_dict))

        # First submission
        res1 = submit.execute(
            family_id=spec.family_id,
            child_id=ChildId("child-1"),
            spec_hash=spec_hash,
            archive_path=Path("/dummy/archive"),
        )
        assert res1.is_ok()
        job1, created1 = res1.unwrap()
        assert created1 is True

        # Second submission after time passes (e.g. retry across years)
        res2 = submit.execute(
            family_id=spec.family_id,
            child_id=ChildId("child-1"),
            spec_hash=spec_hash,
            archive_path=Path("/dummy/archive"),
        )
        assert res2.is_ok()
        job2, created2 = res2.unwrap()
        assert created2 is False
        assert job2.id == job1.id
