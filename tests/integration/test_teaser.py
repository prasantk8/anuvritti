"""TASK-710: the destination is a real, inspectable film, not a placeholder file."""

from __future__ import annotations

import json

import pytest
from filmkit.compositor import probe
from scripts.teaser import render_teaser


@pytest.fixture(scope="module")
def teaser(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("teaser")
    rendered = render_teaser(
        destination=root / "teaser.mp4",
        workspace=root / "work",
        seed_directory=root / "seed",
        receipt=root / "film.json",
        provenance_receipt=root / "provenance.json",
    ).unwrap()
    return root, rendered


def test_ffprobe_agrees_with_the_teasers_compiled_timeline(teaser):
    root, rendered = teaser
    timeline = json.loads((root / "film.json").read_text())["film"]["timeline"]
    inspected = probe(rendered.path)
    streams = inspected["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")

    assert len(streams) == 2
    assert (video["width"], video["height"]) == (timeline["width"], timeline["height"])
    assert float(inspected["format"]["duration"]) == pytest.approx(
        timeline["duration_sec"], abs=1 / timeline["fps"]
    )


def test_a_dozen_real_media_files_became_six_provenance_traced_memories(teaser):
    root, rendered = teaser
    payload = json.loads((root / "film.json").read_text())
    provenance = json.loads((root / "provenance.json").read_text())
    scenes = payload["film"]["timeline"]["scenes"]
    evidence = [scene for scene in scenes if scene["type"] not in {"OPENING", "CLOSING"}]

    assert len(list((root / "seed").glob("*"))) == 12
    assert len(evidence) == 6
    assert len(rendered.frames) == len(scenes) == 8
    assert provenance["unverified_count"] == 0
    assert {entry["scene_id"] for entry in provenance["entries"]} == {
        scene["id"] for scene in evidence
    }
    assert all(frame.path.stat().st_size > 0 for frame in rendered.frames)


def test_the_seed_and_render_live_only_in_the_requested_workspace(teaser):
    root, rendered = teaser
    assert rendered.path == root / "teaser.mp4"
    assert all(root in path.parents for path in (root / "seed").iterdir())
