"""The first pixels: a real export, Chromium, FFmpeg, and an inspected mp4."""

from __future__ import annotations

import base64
import io
import json
import wave
from datetime import date

import pytest
from filmkit.compositor import probe

from anuvritti.adapters.film.export import FilesystemFilmExporter
from anuvritti.adapters.film.render import ChromiumFfmpegRenderer
from anuvritti.domain.voice import VoiceNote
from anuvritti.shared.identity import MediaId
from tests.support.archive import NOW, Archive
from tests.support.fakes import FAMILY, PAPA

pytestmark = pytest.mark.integration

# A real 2x2 RGB PNG. Chromium must decode it; merely copying bytes cannot pass this gate.
PHOTO = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAADCAIAAAA7ljmRAAAACXBIWXMAAAABAAAAAQBPJcTW"
    "AAAAFElEQVR4nGO83pHAAAMsDEgAhQMAQfwByfpiFrIAAAAASUVORK5CYII="
)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("film-render")
    archive = Archive()
    photograph = archive.upload(PHOTO, "image/png")
    archive.moment(
        "first time down the slide alone",
        on=date(2026, 3, 4),
        photo=photograph,
    )
    recording = io.BytesIO()
    with wave.open(recording, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48_000)
        audio.writeframes(b"\x00\x00" * 24_000)
    recording_id = archive.upload(recording.getvalue(), "audio/wav")
    archive.voice_notes.save(
        VoiceNote.kept(
            media_id=MediaId(recording_id),
            family_id=FAMILY,
            author_id=PAPA,
            duration_seconds=0.5,
            at=NOW,
        ).unwrap()
    )
    archive.moment(
        "the song with no words yet",
        on=date(2026, 5, 19),
        audio=recording_id,
    )
    package = archive.compile().unwrap()
    exported = FilesystemFilmExporter(archive.media).export(package, into=root / "export").unwrap()

    result = (
        ChromiumFfmpegRenderer(workspace=root / "work")
        .render(
            exported.directory,
            destination=root / "anuvritti.mp4",
        )
        .unwrap()
    )
    return exported, result


def test_ffprobe_agrees_with_the_compiled_timeline(rendered):
    exported, result = rendered
    payload = json.loads(exported.film_path.read_text())
    timeline = payload["film"]["timeline"]
    inspected = probe(result.path)

    streams = inspected["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next(stream for stream in streams if stream["codec_type"] == "audio")

    assert len(streams) == 2
    assert (video["width"], video["height"]) == (
        timeline["width"],
        timeline["height"],
    )
    assert audio["sample_rate"] == "48000"
    assert float(inspected["format"]["duration"]) == pytest.approx(
        timeline["duration_sec"], abs=1 / timeline["fps"]
    )


def test_every_drawn_frame_traces_to_a_real_scene_in_film_json(rendered):
    exported, result = rendered
    payload = json.loads(exported.film_path.read_text())
    scenes = {scene["id"] for scene in payload["film"]["timeline"]["scenes"]}

    assert result.frames
    assert {frame.scene_id for frame in result.frames} == scenes
    assert all(frame.path.is_file() and frame.path.suffix == ".png" for frame in result.frames)
    assert all(
        frame["image"] == f"{scene['id']}.png"
        for scene in payload["film"]["timeline"]["scenes"]
        for frame in scene["frames"]
    )


def test_the_scene_document_is_a_complete_offline_world(rendered):
    _, result = rendered
    photographed = next(frame for frame in result.frames if frame.scene_id.startswith("moment-"))
    document = photographed.document_path.read_text()

    assert "<style>" in document
    assert "--w-color-ground" in document
    assert "data:font/woff2;base64," in document
    assert "data:image/png;base64," in document
    assert "https://" not in document
    assert 'href="world.css"' not in document
