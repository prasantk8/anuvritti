"""filmkit - compile a timeline of narrated scenes into a film.

What it knows
-------------
Voices have length and that length is measured. Scenes hold for as long as
their voice does, plus whatever padding was asked for. Identical pictures are
drawn once. Nothing is re-encoded that has not changed. Captions come from the
same words the voice said. A frame carries the citations it was built from.

What it does not know
---------------------
Anything about the film. filmkit has never heard of the software whose output
it is showing, or of the year of a life it is assembling. It is handed beats,
lines, shots and a workspace; it hands back a timeline, a set of measurements
and a video. Every product-shaped decision - what a scene means, where the
words came from, what a citation refers to, where files live - is made by the
caller and passed in.

That is not modesty. A package that knows one product can only ever serve that
product, and the second film is where a film compiler either becomes a library
or becomes a fork.
"""

from __future__ import annotations

from .browser import ChromiumPainter, FrameFarm, Painter, Shot, frame_key
from .cachestore import StoreReport, clear, human, prune, survey, touch
from .captions import cues, write_srt, write_vtt
from .compositor import concat_scenes, probe, render_scene, render_scenes, transcode_webm
from .files import atomic_copy, disk_usage, ensure_dir
from .hashing import sha256_bytes, sha256_file, sha256_text, stable_key
from .narration import (
    RECORDED,
    SYNTHETIC,
    Line,
    Narration,
    NarrationError,
    Studio,
    Synthesiser,
    Voice,
    adopt,
    cache_key,
    count_words,
    measure,
)
from .process import CommandError, CommandResult, Runner, run, tool_version, which
from .reporting import HIT, MISS, Recorder, Reporter, Silent
from .timeline import FrameEntry, SceneEntry, Timeline
from .timing import Beat, SceneTiming, TimingReport, plan, visual_seconds
from .workspace import Workspace

__version__ = "0.1.0"

__all__ = [
    "HIT",
    "MISS",
    "RECORDED",
    "SYNTHETIC",
    "Beat",
    "ChromiumPainter",
    "CommandError",
    "CommandResult",
    "FrameEntry",
    "FrameFarm",
    "Line",
    "Narration",
    "NarrationError",
    "Painter",
    "Recorder",
    "Reporter",
    "Runner",
    "SceneEntry",
    "SceneTiming",
    "Shot",
    "Silent",
    "StoreReport",
    "Studio",
    "Synthesiser",
    "Timeline",
    "TimingReport",
    "Voice",
    "Workspace",
    "__version__",
    "adopt",
    "atomic_copy",
    "cache_key",
    "clear",
    "concat_scenes",
    "count_words",
    "cues",
    "disk_usage",
    "ensure_dir",
    "frame_key",
    "human",
    "measure",
    "plan",
    "probe",
    "prune",
    "render_scene",
    "render_scenes",
    "run",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "stable_key",
    "survey",
    "tool_version",
    "touch",
    "transcode_webm",
    "visual_seconds",
    "which",
    "write_srt",
    "write_vtt",
]
