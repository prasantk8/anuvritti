"""The timeline: the single source of truth for composition.

Everything upstream - narration, timing, frames - converges here; everything
downstream - the compositor, the captions, the manifest - reads only this.
Keeping it explicit is what stops the compositor from re-deriving durations and
quietly disagreeing with the timing report.

Two fields carry provenance rather than picture. `shows` names what a scene put
on screen, and `cites` carries the identifiers a reviewer can follow back to
whatever the scene claims to be evidence of. filmkit never interprets either -
it does not know what a citation refers to - but it refuses to drop them,
because a frame that cannot say where it came from is the thing a compiler like
this exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .files import ensure_dir

AUDIO_SLACK_SEC = 1e-6


@dataclass(slots=True)
class FrameEntry:
    """One visible state, and how long it holds."""

    image: str
    duration_sec: float
    label: str

    def to_json(self) -> dict[str, Any]:
        return {
            "image": self.image,
            "duration_sec": round(self.duration_sec, 4),
            "label": self.label,
        }


@dataclass(slots=True)
class SceneEntry:
    id: str
    type: str
    start_sec: float
    audio_path: str
    audio_duration_sec: float
    visual_duration_sec: float
    frames: list[FrameEntry]
    narration: str
    shows: list[str] = field(default_factory=list)
    cites: list[dict[str, Any]] = field(default_factory=list)

    @property
    def delta(self) -> float:
        """Visual minus audio. Positive is padding; negative would be a cut."""
        return self.visual_duration_sec - self.audio_duration_sec

    @property
    def frame_total(self) -> float:
        return sum(frame.duration_sec for frame in self.frames)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "start_sec": round(self.start_sec, 4),
            "audio_path": self.audio_path,
            "audio_duration": round(self.audio_duration_sec, 4),
            "visual_duration": round(self.visual_duration_sec, 4),
            "delta": round(self.delta, 4),
            "frame_duration_total": round(self.frame_total, 4),
            "frame_count": len(self.frames),
            "shows": self.shows,
            "narration": self.narration,
            "cites": self.cites,
            "frames": [frame.to_json() for frame in self.frames],
        }


@dataclass(slots=True)
class Timeline:
    project: str
    fps: int
    width: int
    height: int
    scenes: list[SceneEntry]

    @property
    def duration_sec(self) -> float:
        return sum(scene.visual_duration_sec for scene in self.scenes)

    def to_json(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "resolution": f"{self.width}x{self.height}",
            "duration_sec": round(self.duration_sec, 4),
            "scene_count": len(self.scenes),
            "scenes": [scene.to_json() for scene in self.scenes],
        }

    def write(self, path: Path) -> Path:
        ensure_dir(path.parent)
        path.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False))
        return path

    def check_sync(self, tolerance_sec: float) -> list[str]:
        """Frame durations must add up to the scene they belong to.

        Both halves of this are the same refusal. A drift is reported rather
        than absorbed, and audio longer than its scene is named as truncation
        rather than trimmed - because trimming it is what makes a sentence
        disappear from a finished film without anything in the build saying so.
        """
        problems = []
        for scene in self.scenes:
            drift = abs(scene.frame_total - scene.visual_duration_sec)
            if drift > tolerance_sec:
                problems.append(
                    f"{scene.id}: frames total {scene.frame_total:.3f}s but scene is "
                    f"{scene.visual_duration_sec:.3f}s (drift {drift:.3f}s)"
                )
            if scene.audio_duration_sec > scene.visual_duration_sec + AUDIO_SLACK_SEC:
                problems.append(
                    f"{scene.id}: audio {scene.audio_duration_sec:.3f}s exceeds visual "
                    f"{scene.visual_duration_sec:.3f}s - narration would be cut off"
                )
        return problems
