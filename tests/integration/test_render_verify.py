"""A rendered film can prove that it still matches its portable receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from filmkit.process import run

from anuvritti.adapters.film.verify import OfflineFilmVerifier

pytestmark = pytest.mark.integration


def _digest(path: Path) -> dict[str, object]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@pytest.fixture
def receipt(tmp_path: Path) -> tuple[Path, Path, Path]:
    film = tmp_path / "family-film.mp4"
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
            "color=c=#f7f2e8:s=160x90:r=25:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(film),
        ],
        timeout=30,
        check=True,
    )
    frames = tmp_path / "held-frames"
    frames.mkdir()
    frame = frames / "opening.png"
    frame.write_bytes(b"a retained frame")
    manifest = tmp_path / "family-film.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "anuvritti.render-manifest.v1",
                "timeline": {
                    "fps": 25,
                    "width": 160,
                    "height": 90,
                    "duration_seconds": 1.0,
                },
                "frames": [{"scene_id": "opening", **_digest(frame)}],
                "output": {**_digest(film), "duration_seconds": 1.0},
            }
        ),
        encoding="utf-8",
    )
    return manifest, film, frames


def test_verifies_mp4_and_every_retained_frame_without_the_archive(receipt):
    manifest, film, frames = receipt

    report = OfflineFilmVerifier().verify(manifest, frames=frames).unwrap()

    assert report.film == film
    assert report.checked == (film, frames / "opening.png")
    assert report.retained_frames == 1


def test_frames_are_optional_but_the_report_says_they_were_not_checked(receipt):
    manifest, film, _ = receipt

    report = OfflineFilmVerifier().verify(manifest).unwrap()

    assert report.checked == (film,)
    assert report.retained_frames == 0
    assert report.skipped == ("1 retained frame was not supplied",)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("film", "changed artifact family-film.mp4: byte count"),
        ("frame", "changed artifact opening.png: sha256"),
    ],
)
def test_names_the_exact_artifact_and_evidence_that_changed(receipt, target, expected):
    manifest, film, frames = receipt
    path = film if target == "film" else frames / "opening.png"
    body = path.read_bytes()
    path.write_bytes(body + b"changed" if target == "film" else b"A" + body[1:])

    error = OfflineFilmVerifier().verify(manifest, frames=frames).unwrap_err()

    assert error.details["findings"][0].startswith(expected)


def test_distinguishes_a_missing_retained_frame_from_changed_bytes(receipt):
    manifest, _, frames = receipt
    (frames / "opening.png").unlink()

    error = OfflineFilmVerifier().verify(manifest, frames=frames).unwrap_err()

    assert error.details["findings"] == ["missing artifact opening.png"]


def test_ffprobe_must_agree_with_the_timeline_even_when_the_hash_receipt_does(receipt):
    manifest, _, _ = receipt
    payload = json.loads(manifest.read_text())
    payload["timeline"]["width"] = 161
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    error = OfflineFilmVerifier().verify(manifest).unwrap_err()

    assert error.details["findings"] == [
        "invalid film family-film.mp4: frame size 160x90 does not match timeline 161x90"
    ]


def test_manifest_paths_cannot_escape_the_receipt_directory(receipt):
    manifest, _, _ = receipt
    payload = json.loads(manifest.read_text())
    payload["output"]["path"] = "../some-other-film.mp4"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    error = OfflineFilmVerifier().verify(manifest).unwrap_err()

    assert error.details["findings"] == [
        "invalid manifest: output.path must be a portable file name"
    ]


def test_an_unreadable_video_is_an_error_value_not_an_exception(receipt):
    manifest, film, _ = receipt
    film.write_bytes(b"not a video")
    payload = json.loads(manifest.read_text())
    payload["output"].update(_digest(film))
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    error = OfflineFilmVerifier().verify(manifest).unwrap_err()

    assert error.details["findings"] == ["ffprobe refused the film: 1"]
