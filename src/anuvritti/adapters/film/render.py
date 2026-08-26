"""Draw a portable FilmExport with Chromium, then compose it with FFmpeg.

The family server never imports this adapter. It belongs on the temporary render machine:
the one allowed to hold plaintext export bytes, a browser, and an encoder. Before drawing,
it rechecks the hashes and the provenance ledger because an export may have travelled since
the compiler vouched for it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

from filmkit.browser import FrameFarm, Shot
from filmkit.compositor import concat_scenes, probe, render_scene, render_scenes
from filmkit.process import run
from filmkit.timeline import FrameEntry, SceneEntry, Timeline
from filmkit.workspace import Workspace

from anuvritti.application.ports import RenderedFilm, RenderedFrame
from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

_REPOSITORY = Path(__file__).resolve().parents[4]
_WORLD_RENDERER = _REPOSITORY / "packages" / "world" / "scripts" / "render-film.ts"
_FILM = "film.json"
_PROVENANCE = "provenance.json"
_MEDIA = "media"
_IMAGE = "IMAGE"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class _Export:
    film: dict[str, Any]
    timeline: dict[str, Any]
    bundle: dict[str, Any]
    media: dict[str, Path]


class ChromiumFfmpegRenderer:
    """One still per scene, real silence where nobody speaks, and one final mp4."""

    __slots__ = ("_workers", "_workspace_root")

    def __init__(self, *, workspace: Path, workers: int = 1) -> None:
        self._workspace_root = workspace
        self._workers = max(1, workers)

    def render(self, archive: Path, *, destination: Path) -> Result[RenderedFilm, DomainError]:
        try:
            exported = _read_and_verify(archive)
            workspace = Workspace.under(self._workspace_root)
            documents = workspace.artifact("documents")
            frames_dir = workspace.artifact("frames")
            scenes_dir = workspace.artifact("scenes")

            scene_inputs = _scene_inputs(exported)
            batch = workspace.artifacts / "world-scenes.json"
            batch.parent.mkdir(parents=True, exist_ok=True)
            batch.write_text(json.dumps({"scenes": scene_inputs}), encoding="utf-8")
            run(
                ["node", str(_WORLD_RENDERER), str(batch), str(documents)],
                timeout=120,
                check=True,
            )

            timeline = _timeline(exported, frames_dir, scenes_dir)
            shots, rendered_frames = _shots(timeline, documents)
            FrameFarm(
                timeline.width,
                timeline.height,
                {"world": "packages/world", "theme": "light"},
                workspace=workspace,
                workers=self._workers,
                # A Chromium revision is tied to its Playwright release. Including that
                # release prevents pixels drawn by a different browser entering this cache.
                renderer=f"anuvritti-frames-1-playwright-{version('playwright')}",
            ).render(shots)

            scene_files = render_scenes(
                timeline.scenes,
                timeline,
                scenes_dir,
                workers=self._workers,
                render=lambda scene, plan, work, **kwargs: render_scene(
                    scene, plan, work, workspace=workspace, **kwargs
                ),
            )
            concat_scenes(scene_files, destination, scenes_dir)
            inspected = probe(destination)
            duration = _verify_output(inspected, timeline)
            return Ok(RenderedFilm(destination, rendered_frames, duration))
        except Exception as exc:
            return Err(
                DomainError(
                    ErrorCode.FILM_NOT_COMPILABLE,
                    "the exported film could not be rendered without changing what it says",
                    {"archive": str(archive), "reason": str(exc)},
                )
            )


def _read_and_verify(archive: Path) -> _Export:
    payload = _object(json.loads((archive / _FILM).read_text(encoding="utf-8")), _FILM)
    film = _object(payload["film"], "film")
    timeline = _object(film["timeline"], "film.timeline")
    bundle = _object(payload["bundle"], "bundle")
    provenance = _object(
        json.loads((archive / _PROVENANCE).read_text(encoding="utf-8")), _PROVENANCE
    )

    scenes = _objects(timeline["scenes"], "film.timeline.scenes")
    compiled = _objects(film["scenes"], "film.scenes")
    for scene in scenes:
        _safe_name(str(scene["id"]), "scene id")
    if [scene["id"] for scene in scenes] != [scene["id"] for scene in compiled]:
        raise ValueError("the timeline and compiled film name different scenes")

    claimed = {
        (str(scene["id"]), str(cite["kind"]), str(cite["id"]))
        for scene in scenes
        for cite in _objects(scene["cites"], f"{scene['id']}.cites")
    }
    entries = _objects(provenance["entries"], "provenance.entries")
    checked = {
        (str(entry["scene_id"]), str(cite["kind"]), str(cite["id"]))
        for entry in entries
        for cite in [_object(entry["cites"], "provenance entry citation")]
        if entry.get("status") == "VERIFIED"
    }
    if claimed != checked or int(provenance["unverified_count"]) != 0:
        raise ValueError("the provenance ledger does not verify every scene citation exactly")

    media: dict[str, Path] = {}
    for item in _objects(bundle["items"], "bundle.items"):
        media_id = str(item["id"])
        _safe_name(media_id, "media id")
        matches = [path for path in (archive / _MEDIA).iterdir() if path.stem == media_id]
        if len(matches) != 1:
            raise ValueError(f"bundle media {media_id} does not resolve to exactly one file")
        body = matches[0].read_bytes()
        if len(body) != int(item["byte_size"]):
            raise ValueError(f"bundle media {media_id} changed size after export")
        if hashlib.sha256(body).hexdigest() != item["content_hash"]:
            raise ValueError(f"bundle media {media_id} changed after export")
        media[media_id] = matches[0]
    return _Export(film, timeline, bundle, media)


def _scene_inputs(exported: _Export) -> list[dict[str, str]]:
    media_items = {
        str(item["id"]): item for item in _objects(exported.bundle["items"], "bundle.items")
    }
    inputs: list[dict[str, str]] = []
    for scene in _objects(exported.timeline["scenes"], "timeline.scenes"):
        shows = [str(value) for value in cast(list[object], scene["shows"])]
        value = {
            "id": str(scene["id"]),
            "kind": str(scene["type"]),
            "heading": shows[0] if shows else "",
        }
        if len(shows) > 1:
            value["body"] = shows[1]
        narration = str(scene["narration"])
        if narration:
            value["narration"] = narration

        for cite in _objects(scene["cites"], f"{scene['id']}.cites"):
            media_id = str(cite["id"])
            item = media_items.get(media_id)
            if cite["kind"] != "MEDIA" or item is None or item["kind"] != _IMAGE:
                continue
            mime = str(item["mime_type"])
            encoded = base64.b64encode(exported.media[media_id].read_bytes()).decode("ascii")
            value["picture"] = f"data:{mime};base64,{encoded}"
            break
        inputs.append(value)
    return inputs


def _timeline(exported: _Export, frames: Path, scenes: Path) -> Timeline:
    source = exported.timeline
    entries: list[SceneEntry] = []
    for scene in _objects(source["scenes"], "timeline.scenes"):
        scene_id = str(scene["id"])
        duration = float(scene["visual_duration"])
        audio_id = str(scene["audio_path"])
        audio = exported.media.get(audio_id) if audio_id else None
        if audio_id and audio is None:
            raise ValueError(f"{scene_id} names audio {audio_id}, but the bundle does not carry it")
        if audio is None:
            audio = scenes / f"{scene_id}-silence.wav"
            _silence(audio, duration)
        entries.append(
            SceneEntry(
                id=scene_id,
                type=str(scene["type"]),
                start_sec=float(scene["start_sec"]),
                audio_path=str(audio),
                audio_duration_sec=float(scene["audio_duration"]),
                visual_duration_sec=duration,
                frames=[FrameEntry(str(frames / f"{scene_id}.png"), duration, scene_id)],
                narration=str(scene["narration"]),
                shows=[str(value) for value in cast(list[object], scene["shows"])],
                cites=_objects(scene["cites"], f"{scene_id}.cites"),
            )
        )
    timeline = Timeline(
        project=str(source["project"]),
        fps=int(source["fps"]),
        width=int(source["width"]),
        height=int(source["height"]),
        scenes=entries,
    )
    problems = timeline.check_sync(tolerance_sec=1e-4)
    if problems:
        raise ValueError("; ".join(problems))
    return timeline


def _silence(destination: Path, seconds: float) -> None:
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
            "anullsrc=r=48000:cl=stereo",
            "-t",
            f"{seconds:.6f}",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        timeout=120,
        check=True,
    )


def _shots(timeline: Timeline, documents: Path) -> tuple[list[Shot], tuple[RenderedFrame, ...]]:
    shots: list[Shot] = []
    frames: list[RenderedFrame] = []
    for scene in timeline.scenes:
        document_path = documents / f"{scene.id}.html"
        frame_path = Path(scene.frames[0].image)
        document = document_path.read_text(encoding="utf-8")
        shots.append(
            Shot(
                destination=frame_path,
                html=document,
                key_payload={"scene_id": scene.id, "cites": scene.cites},
                duration_sec=scene.visual_duration_sec,
                label=scene.id,
            )
        )
        frames.append(RenderedFrame(scene.id, frame_path, document_path))
    return shots, tuple(frames)


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} is not an object")
    return cast(dict[str, Any], value)


def _objects(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError(f"{name} is not a list")
    return [_object(item, name) for item in value]


def _safe_name(value: str, name: str) -> str:
    if not _SAFE_NAME.fullmatch(value):
        raise ValueError(f"{name} {value!r} is not a portable file name")
    return value


def _verify_output(inspected: dict[str, Any], timeline: Timeline) -> float:
    streams = _objects(inspected["streams"], "ffprobe.streams")
    if len(streams) != 2:
        raise ValueError(f"ffprobe found {len(streams)} streams instead of video plus audio")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise ValueError("ffprobe did not find exactly one video stream and one audio stream")
    video = videos[0]
    if (int(video["width"]), int(video["height"])) != (timeline.width, timeline.height):
        raise ValueError("the encoded frame size disagrees with the compiled timeline")
    duration = float(_object(inspected["format"], "ffprobe.format")["duration"])
    if abs(duration - timeline.duration_sec) > 1 / timeline.fps:
        raise ValueError("the encoded duration disagrees with the compiled timeline")
    return duration


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a provenance-verified FilmExport")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--still", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path("var/film/work"))
    arguments = parser.parse_args()

    rendered = ChromiumFfmpegRenderer(workspace=arguments.workspace).render(
        arguments.archive, destination=arguments.output
    )
    if rendered.is_err():
        print(rendered.unwrap_err().message)
        print(rendered.unwrap_err().details["reason"])
        return 1
    result = rendered.unwrap()
    if arguments.still and result.frames:
        arguments.still.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.frames[0].path, arguments.still)
    print(f"film  {result.path} ({result.duration_seconds:.3f}s)")
    if arguments.still:
        print(f"still {arguments.still}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by `make film`
    raise SystemExit(main())
