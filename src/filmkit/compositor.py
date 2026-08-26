"""Composition: stills plus voice, per scene, then joined.

Two passes, deliberately:

  1. per scene: still states + that scene's narration -> an intermediate video
  2. all scenes -> the final file, by stream copy

Per scene is what makes an incremental compile possible - an edit to scene six
re-encodes scene six and concatenates. It also isolates a failure to the scene
that caused it, instead of to "the render".

`-shortest` is never used, anywhere, and that is the load-bearing decision in
this file. It resolves a mismatch between picture and voice by silently
discarding whichever ends last, which is precisely the fault a compiler like
this exists to surface. Audio is padded to the scene length with real silence
instead, so a drift becomes a measurable delta in the timeline rather than a
sentence that quietly stops.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import cachestore
from .files import atomic_copy, ensure_dir
from .hashing import sha256_file, stable_key
from .process import Runner, run
from .reporting import HIT, MISS, Recorder, Reporter, Silent
from .timeline import SceneEntry, Timeline
from .workspace import Workspace

# Encoder settings, pinned here rather than at call sites so a manifest can
# record exactly one answer to "how was this encoded".
# fmt: off
# Deliberately not formatted one-item-per-line. To a formatter this is a list of
# strings; to anyone reading it, `"-crf", "18"` is a single fact and splitting it
# across two lines is the difference between a legible encoder setting and a
# column of quoted fragments.
H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
# VP9 is single-threaded per tile by default, which is why a WebM used to take
# longer than the rest of a compile combined. Row threading plus tiles spreads
# one frame across cores; `-cpu-used 2` is the usual "good" point where quality
# is indistinguishable at this CRF.
VP9 = [
    "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "31",
    "-row-mt", "1", "-tile-columns", "2", "-frame-parallel", "0",
    "-deadline", "good", "-cpu-used", "2", "-pix_fmt", "yuv420p",
]
OPUS = ["-c:a", "libopus", "-b:a", "128k"]
# fmt: on

SceneRenderer = Callable[..., Path]


def concat_file(scene: SceneEntry, destination: Path) -> Path:
    """A concat demuxer script: one image per visible state.

    The final entry is repeated without a duration because the demuxer drops
    the last file's duration otherwise - a documented quirk, and the reason a
    scene would come up exactly one frame short if this were left out.
    """
    lines = []
    for frame in scene.frames:
        lines.append(f"file '{Path(frame.image).resolve()}'")
        lines.append(f"duration {frame.duration_sec:.6f}")
    lines.append(f"file '{Path(scene.frames[-1].image).resolve()}'")
    destination.write_text("\n".join(lines) + "\n")
    return destination


def scene_key(scene: SceneEntry, timeline: Timeline) -> str:
    return stable_key(
        {
            "frames": [(Path(f.image).name, round(f.duration_sec, 4)) for f in scene.frames],
            "audio": sha256_file(Path(scene.audio_path)),
            "visual": round(scene.visual_duration_sec, 4),
            "fps": timeline.fps,
            "size": f"{timeline.width}x{timeline.height}",
            "encoder": H264 + AAC,
        }
    )


def render_scene(
    scene: SceneEntry,
    timeline: Timeline,
    work_dir: Path,
    *,
    workspace: Workspace,
    reporter: Reporter | None = None,
    runner: Runner | None = None,
    threads: int = 0,
) -> Path:
    """Encode one scene. Cached on everything that could change the picture."""
    told: Reporter = reporter or Silent()
    call = runner or run
    out = work_dir / f"{scene.id}.mp4"

    key = scene_key(scene, timeline)
    cached = workspace.store("scenes") / f"{key}.mp4"
    if cached.is_file():
        cachestore.touch(cached)
        ensure_dir(out.parent)
        atomic_copy(cached, out)
        told.cache(HIT, f"scene video {scene.id}")
        return out

    told.cache(MISS, f"scene video {scene.id} ({len(scene.frames)} states)")
    concat = concat_file(scene, work_dir / f"{scene.id}.concat")

    # fmt: off
    argv = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(scene.audio_path),
        # Pad the voice with real silence to the scene length. This is what
        # replaces `-shortest`: the two streams are made equal on purpose, and
        # how much padding it took is recorded as the scene's delta.
        "-filter_complex",
        f"[0:v]fps={timeline.fps},format=yuv420p,"
        f"scale={timeline.width}:{timeline.height}:flags=lanczos[v];"
        f"[1:a]aresample=48000,apad[a]",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{scene.visual_duration_sec:.6f}",
        *(["-threads", str(threads)] if threads else []),
        *H264, *AAC,
        "-movflags", "+faststart",
        str(out),
    ]
    # fmt: on
    call(argv, timeout=900, check=True, log_name=f"ffmpeg_scene_{scene.id}")
    atomic_copy(out, cached)
    return out


def render_scenes(
    scenes: list[SceneEntry],
    timeline: Timeline,
    work_dir: Path,
    *,
    reporter: Reporter | None = None,
    workers: int = 1,
    render: SceneRenderer,
) -> list[Path]:
    """Encode every scene, several at a time, and hand them back in order.

    Scenes are independent by construction - that is the point of encoding per
    scene - so the only things this has to preserve are the order of the
    results and the order of what was said about them. Both are restored after
    the pool drains, because interleaved progress from eight encoders is worse
    than no progress at all.

    Each encoder is told how many threads it may take. Left alone, an encoder
    takes the whole machine, and eight copies of it fighting over ten cores is
    slower than eight copies given one core each.
    """
    told: Reporter = reporter or Silent()
    lanes = max(1, min(workers, len(scenes)))
    per_encoder = max(1, (os.cpu_count() or lanes) // lanes)

    if lanes == 1:
        return [
            render(scene, timeline, work_dir, reporter=told, threads=per_encoder)
            for scene in scenes
        ]

    def one(scene: SceneEntry) -> tuple[Path, Recorder]:
        recorder = Recorder()
        path = render(scene, timeline, work_dir, reporter=recorder, threads=per_encoder)
        return path, recorder

    with ThreadPoolExecutor(max_workers=lanes) as pool:
        results = list(pool.map(one, scenes))

    for _, recorder in results:
        recorder.replay(told)
    return [path for path, _ in results]


def concat_scenes(
    scene_files: list[Path],
    destination: Path,
    work_dir: Path,
    *,
    runner: Runner | None = None,
) -> Path:
    """Join finished scenes by stream copy. Nothing is re-encoded here."""
    call = runner or run
    listing = work_dir / "scenes.concat"
    listing.write_text("\n".join(f"file '{path.resolve()}'" for path in scene_files) + "\n")
    ensure_dir(destination.parent)
    # fmt: off
    argv = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart",
        str(destination),
    ]
    # fmt: on
    call(argv, timeout=900, check=True, log_name="ffmpeg_concat")
    return destination


def transcode_webm(
    source: Path,
    destination: Path,
    *,
    workspace: Workspace,
    threads: int = 0,
    reporter: Reporter | None = None,
    runner: Runner | None = None,
) -> Path:
    """VP9/Opus, cached on the video it came from.

    This is the step that is easiest to leave uncached and hardest to notice:
    on a rebuild where nothing changed it can be the entire compile, minutes of
    re-encoding a byte-identical input. The key is the source file's hash plus
    the encoder flags, so a changed video or a changed setting re-encodes and
    nothing else does.
    """
    told: Reporter = reporter or Silent()
    call = runner or run
    key = stable_key({"source": sha256_file(source), "encoder": VP9 + OPUS})
    cached = workspace.store("scenes") / f"webm-{key}.webm"
    if cached.is_file():
        cachestore.touch(cached)
        ensure_dir(destination.parent)
        atomic_copy(cached, destination)
        told.cache(HIT, "webm (VP9/Opus)")
        return destination

    told.cache(MISS, "webm (VP9/Opus)")
    # fmt: off
    argv = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        *(["-threads", str(threads)] if threads else []),
        *VP9, *OPUS,
        str(destination),
    ]
    # fmt: on
    call(argv, timeout=3600, check=True, log_name="ffmpeg_webm")
    atomic_copy(destination, cached)
    return destination


def probe(path: Path, *, runner: Runner | None = None) -> dict[str, Any]:
    """What the container actually holds, from the tool, not from intent."""
    call = runner or run
    result = call(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        timeout=120,
        check=True,
    )
    found: dict[str, Any] = json.loads(result.stdout)
    return found
