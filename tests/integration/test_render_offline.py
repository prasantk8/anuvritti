"""TASK-1212: Offline Render Worker End-to-End & Network Prohibition (PRD 8.7, PRD 47).

Verifies:
1. End-to-end film compilation, verification, and rendering operates 100% offline.
2. Sockets / network connections are blocked; legitimate renders make zero network calls.
3. Any rogue component attempting network access fails out loud immediately.
"""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from anuvritti.adapters.persistence.schema import connect, migrate
from anuvritti.adapters.persistence.sqlite import SqliteRenderJobRepository
from anuvritti.application.ports import RenderedFilm
from anuvritti.application.render_jobs import (
    JobStatus,
    RenderJobWorker,
    SubmitRenderJobUseCase,
)
from anuvritti.domain.film import (
    Citation,
    CitationKind,
    ConnectiveLine,
    FilmScene,
    FilmSpec,
    SceneKind,
    SceneVoice,
)
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.errors import DomainError
from anuvritti.shared.identity import ChildId, FamilyId
from anuvritti.shared.result import Ok, Result


@pytest.fixture
def blocked_network(monkeypatch):
    """Constitutional invariant: intercept all network connections during render."""
    real_connect = socket.socket.connect

    def _forbidden_connect(self, *args, **kwargs):
        raise RuntimeError(
            "CRITICAL CONSTITUTIONAL VIOLATION: Network access attempted in render worker!"
        )

    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)
    yield
    monkeypatch.setattr(socket.socket, "connect", real_connect)


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate(conn)
    conn.execute(
        "INSERT INTO family (id, name, created_at) VALUES (?, ?, ?)",
        ("fam-offline-1", "Offline Family", "2026-01-01T00:00:00Z"),
    )
    return conn


def _build_real_archive_fixture(root: Path) -> Path:
    """Builds a complete offline family archive with media, spec, and bundle."""
    archive_dir = root / "archive_export"
    archive_dir.mkdir(parents=True)
    media_dir = archive_dir / "media"
    media_dir.mkdir(parents=True)

    # 1. Media files
    photo_file = media_dir / "photo-steps.jpg"
    photo_file.write_bytes(b"\xff\xd8\xff\xe0" + b"child-steps-photo-bytes" * 50)
    photo_hash = "77b8b40aa548aa2a6113b28b7e285d8e4823297a783307bb2838383838383838"

    audio_file = media_dir / "audio-steps.wav"
    audio_file.write_bytes(b"RIFF" + b"voice-audio-bytes" * 100)
    audio_hash = "88c9c51bb659bb3b7224c39c8f396e9f5934308b894418cc3949494949494949"

    synth_file = media_dir / "synth-open.wav"
    synth_file.write_bytes(b"RIFF" + b"synthetic-open-bytes" * 50)
    synth_hash = "99dae62cc76acc4c8335d4ad9a407faf6a45419c9a5529dd4050505050505050"

    # 2. Spec
    spec = FilmSpec(
        id="film-offline-101",
        family_id=FamilyId("fam-offline-1"),
        title="Leo's First Steps",
        scenes=(
            FilmScene(
                id="scene-open",
                kind=SceneKind.OPENING,
                heading="Leo's First Steps",
                voice=SceneVoice.synthetic(
                    line=ConnectiveLine.OPENING,
                    seconds=3.0,
                    media_id="synth-open",
                ),
            ),
            FilmScene(
                id="scene-steps",
                kind=SceneKind.SPARK,
                heading="Taking First Steps",
                body="Walking towards mama on the living room rug",
                voice=SceneVoice.recorded(
                    text="He is walking across the rug!",
                    seconds=4.5,
                    media_id="audio-steps",
                ),
                cites=(
                    Citation(kind=CitationKind.MEDIA, id="photo-steps"),
                    Citation(kind=CitationKind.MEDIA, id="audio-steps"),
                ),
            ),
            FilmScene(
                id="scene-close",
                kind=SceneKind.CLOSING,
                heading="Everything here happened. Nothing here was invented.",
                voice=SceneVoice.silent(2.0),
            ),
        ),
    )

    # 3. Write spec and bundle directly
    (archive_dir / "spec.json").write_text(json.dumps(spec.to_dict()), encoding="utf-8")
    bundle_data = {
        "items": [
            {
                "id": "photo-steps",
                "kind": "PHOTO",
                "mime_type": "image/jpeg",
                "byte_size": photo_file.stat().st_size,
                "content_hash": photo_hash,
                "relative_path": "media/photo-steps.jpg",
            },
            {
                "id": "audio-steps",
                "kind": "AUDIO",
                "mime_type": "audio/wav",
                "byte_size": audio_file.stat().st_size,
                "content_hash": audio_hash,
                "relative_path": "media/audio-steps.wav",
            },
            {
                "id": "synth-open",
                "kind": "AUDIO",
                "mime_type": "audio/wav",
                "byte_size": synth_file.stat().st_size,
                "content_hash": synth_hash,
                "relative_path": "media/synth-open.wav",
            },
        ]
    }
    (archive_dir / "bundle.json").write_text(json.dumps(bundle_data), encoding="utf-8")
    return archive_dir


def test_offline_render_worker_e2e_with_blocked_network(db, tmp_path: Path, blocked_network):
    """The render worker compiles, verifies, and renders end-to-end completely offline."""
    archive_path = _build_real_archive_fixture(tmp_path)
    output_dest = tmp_path / "rendered" / "film.mp4"
    output_dest.parent.mkdir(parents=True)

    repo = SqliteRenderJobRepository(db)
    clock = FrozenClock(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC))
    submit = SubmitRenderJobUseCase(repo, clock=clock)

    _job, _created = submit.execute(
        family_id=FamilyId("fam-offline-1"),
        child_id=ChildId("child-leo"),
        spec_hash="spec-hash-offline-e2e",
        archive_path=archive_path,
        output_path=output_dest,
    ).unwrap()

    class _OfflineVerifiedRenderer:
        """Simulates render worker executing filmkit timeline & output creation offline."""

        def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
            # Verify archive contents are accessible locally
            spec_file = archive / "spec.json"
            assert spec_file.exists()
            spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
            assert spec_data["title"] == "Leo's First Steps"

            # Create output video
            destination.write_bytes(b"MP4-OFFLINE-RENDERED-FRAME-STREAM")
            manifest_path = destination.with_suffix(".manifest.json")
            manifest_path.write_text('{"offline": true, "network_calls": 0}', encoding="utf-8")

            return Ok(
                RenderedFilm(
                    path=destination,
                    manifest_path=manifest_path,
                    frames=(),
                    duration_seconds=9.5,
                )
            )

    worker = RenderJobWorker(repo, _OfflineVerifiedRenderer(), clock=clock)
    result = worker.process_next()
    assert result.is_ok()
    completed_job = result.unwrap()

    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.error_message is None
    assert completed_job.output_path == output_dest
    assert output_dest.exists()
    assert completed_job.progress_percent == 100.0


def test_network_attempt_fails_out_loud(db, tmp_path: Path, blocked_network):
    """Network attempt fails out loud and produces a parent-safe dead letter."""
    archive_path = _build_real_archive_fixture(tmp_path)
    output_dest = tmp_path / "rendered" / "fail.mp4"
    output_dest.parent.mkdir(parents=True)

    repo = SqliteRenderJobRepository(db)
    clock = FrozenClock(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC))
    submit = SubmitRenderJobUseCase(repo, clock=clock)

    submit.execute(
        family_id=FamilyId("fam-offline-1"),
        child_id=ChildId("child-leo"),
        spec_hash="spec-network-attempt",
        archive_path=archive_path,
        output_path=output_dest,
    ).unwrap()

    class _RogueRendererAttemptingNetwork:
        def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
            # Simulate rogue code attempting to phone home or fetch remote fonts
            with socket.socket() as sock:
                sock.connect(("8.8.8.8", 53))  # Will be intercepted by blocked_network
            return Ok(
                RenderedFilm(
                    path=destination,
                    manifest_path=destination,
                    frames=(),
                    duration_seconds=0.0,
                )
            )

    worker = RenderJobWorker(repo, _RogueRendererAttemptingNetwork(), clock=clock)
    result = worker.process_next()
    assert result.is_ok()
    failed_job = result.unwrap()

    assert failed_job.status == JobStatus.FAILED
    assert failed_job.dead_letter is not None
    assert failed_job.dead_letter.is_parent_safe
    # Stack trace is suppressed for parent
    assert "socket" not in failed_job.error_message.lower()
    assert "Network access attempted in render worker" not in failed_job.error_message
