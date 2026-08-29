"""The first pixels: a real export, Chromium, FFmpeg, and an inspected mp4."""

from __future__ import annotations

import base64
import io
import json
import shutil
import wave
from datetime import date
from hashlib import sha256

import pytest
from filmkit.browser import FrameFarm
from filmkit.compositor import probe
from playwright.sync_api import sync_playwright

from anuvritti.adapters.film.export import FilesystemFilmExporter
from anuvritti.adapters.film.render import ChromiumFfmpegRenderer, _verify_bundled_fonts
from anuvritti.application.ports import RenderedFrame
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
    archive.moment("أول مرة نزل فيها وحده", on=date(2026, 3, 5))
    archive.moment("पहली बार वह अकेले फिसला", on=date(2026, 3, 6))
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
    payload = json.loads(exported.film_path.read_text())
    multilingual_bodies = {
        "أول مرة نزل فيها وحده": "قالها بابا",
        "पहली बार वह अकेले फिसला": "पापा ने लिखा",
    }
    for scene in payload["film"]["timeline"]["scenes"]:
        if scene["shows"][0] in multilingual_bodies:
            scene["shows"].append(multilingual_bodies[scene["shows"][0]])
    exported.film_path.write_text(json.dumps(payload))

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


def test_manifest_accounts_for_the_tools_sources_commands_and_every_pixel(rendered):
    exported, result = rendered
    manifest = json.loads(result.manifest_path.read_text())
    timeline = json.loads(exported.film_path.read_text())["film"]["timeline"]

    assert result.manifest_path == result.path.with_suffix(".manifest.json")
    assert manifest["schema"] == "anuvritti.render-manifest.v1"
    assert (
        manifest["sources"]["film.json"]["sha256"]
        == sha256(exported.film_path.read_bytes()).hexdigest()
    )
    assert (
        manifest["sources"]["provenance.json"]["sha256"]
        == sha256(exported.provenance_path.read_bytes()).hexdigest()
    )
    assert manifest["toolchain"]["playwright"]
    assert manifest["toolchain"]["chromium"]["version"]
    assert manifest["toolchain"]["chromium"]["revision"]
    assert "ffmpeg version" in manifest["toolchain"]["ffmpeg"]

    assert manifest["output"]["path"] == result.path.name
    assert manifest["output"]["sha256"] == sha256(result.path.read_bytes()).hexdigest()
    assert len(manifest["commands"]["scene_encodes"]) == len(timeline["scenes"])
    assert manifest["commands"]["concat"][0] == "ffmpeg"
    assert all("/Users/" not in json.dumps(command) for command in manifest["commands"].values())

    scenes = {scene["id"] for scene in timeline["scenes"]}
    frames = {entry["scene_id"]: entry for entry in manifest["frames"]}
    assert frames.keys() == scenes
    for frame in result.frames:
        assert frames[frame.scene_id]["path"] == frame.path.name
        assert frames[frame.scene_id]["sha256"] == sha256(frame.path.read_bytes()).hexdigest()


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


def test_arabic_and_devanagari_glyphs_are_drawn_only_from_bundled_fonts(rendered):
    _, result = rendered
    documents = "\n".join(frame.document_path.read_text() for frame in result.frames)
    manifest = json.loads(result.manifest_path.read_text())

    assert "Noto Naskh Arabic" in documents
    assert "Noto Serif Devanagari" in documents
    assert "Noto Sans Arabic" in documents
    assert "Noto Sans Devanagari" in documents
    assert manifest["fonts"]["scripts"] == ["Latin", "Arabic", "Devanagari"]
    assert {font["script"] for font in manifest["fonts"]["faces"]} == {
        "Latin",
        "Arabic",
        "Devanagari",
    }
    assert all(font["sha256"] and font["bytes"] > 0 for font in manifest["fonts"]["faces"])

    samples = {
        "أول مرة نزل فيها وحده": ("h1", "Noto Naskh Arabic"),
        "قالها بابا": ("p", "Noto Sans Arabic"),
        "पहली बार वह अकेले फिसला": ("h1", "Noto Serif Devanagari"),
        "पापा ने लिखा": ("p", "Noto Sans Devanagari"),
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for sample, (selector, expected_family) in samples.items():
                frame = next(
                    item for item in result.frames if sample in item.document_path.read_text()
                )
                page = browser.new_page()
                try:
                    page.set_content(frame.document_path.read_text(), wait_until="load")
                    session = page.context.new_cdp_session(page)
                    session.send("DOM.enable")
                    session.send("CSS.enable")
                    document = session.send("DOM.getDocument")
                    heading = session.send(
                        "DOM.querySelector",
                        {"nodeId": document["root"]["nodeId"], "selector": selector},
                    )
                    fonts = session.send(
                        "CSS.getPlatformFontsForNode", {"nodeId": heading["nodeId"]}
                    )["fonts"]
                    assert expected_family in {font["familyName"] for font in fonts}
                    assert all(font["isCustomFont"] for font in fonts)
                    assert all(font["glyphCount"] > 0 for font in fonts)
                finally:
                    page.close()
        finally:
            browser.close()


def test_an_unbundled_writing_system_is_refused_before_chromium(rendered, tmp_path, monkeypatch):
    exported, _ = rendered
    archive = tmp_path / "export"
    shutil.copytree(exported.directory, archive)
    film_path = archive / "film.json"
    payload = json.loads(film_path.read_text())
    payload["film"]["timeline"]["scenes"][0]["shows"][0] = "家"
    film_path.write_text(json.dumps(payload))

    def chromium_must_not_start(*_args, **_kwargs):
        raise AssertionError("Chromium started for an unsupported writing system")

    monkeypatch.setattr(FrameFarm, "render", chromium_must_not_start)

    destination = tmp_path / "unsupported.mp4"
    refused = ChromiumFfmpegRenderer(workspace=tmp_path / "work").render(
        archive, destination=destination
    )

    assert refused.is_err()
    assert "U+5BB6" in refused.unwrap_err().details["reason"]
    assert not destination.exists()


def test_a_host_font_is_refused_instead_of_becoming_part_of_a_frame(tmp_path):
    document = tmp_path / "borrowed.html"
    document.write_text("<style>h1{font-family:sans-serif}</style><h1>remembered</h1>")
    frame = RenderedFrame("borrowed", tmp_path / "borrowed.png", document)

    with pytest.raises(ValueError, match="borrow unbundled host font"):
        _verify_bundled_fonts((frame,))
