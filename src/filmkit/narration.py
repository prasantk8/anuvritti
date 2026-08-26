"""Narration: measured, never estimated - and honest about whose voice it is.

Audio is the timing authority. Everything visual in a film compiled here is cut
to fit the voice, which only works if the voice's length is a *measurement*.
A word count divided by a words-per-minute target is a prediction; it is useful
for saying "this script will not fit", and it is never allowed to decide how
long anything stays on screen.

Two origins, one measurement
----------------------------
A narration track is either RECORDED - a real person, already on disk - or
SYNTHETIC, generated from text. Both are measured the same way, by probing the
finished file. The difference is recorded on every track and survives into the
manifest, because "who is speaking" is a question a film should be able to
answer about itself, and a synthesiser that quietly stands in for a person is
the exact failure that makes the answer worthless.

Synthesis reaches a network service, which is a reproducibility liability. The
mitigation is the cache: once a line's audio exists under its content address,
a rebuild never calls out again, and `offline=True` refuses to synthesise
anything that is not already cached - which is what a CI run should use.
"""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .files import atomic_copy
from .hashing import sha256_file, stable_key
from .process import Runner, run
from .reporting import HIT, MISS, Reporter, Silent
from .workspace import Workspace

RECORDED = "recorded"
SYNTHETIC = "synthetic"

WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019\-]*")


def count_words(text: str) -> int:
    """Words as a listener would count them, for the estimate that never renders."""
    return len(WORD_RE.findall(text))


class NarrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Voice:
    """Who is speaking, and how. Part of every synthesis cache key."""

    name: str
    rate: str = "+0%"
    pitch: str = "+0Hz"

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Voice:
        return cls(
            name=values["name"],
            rate=values.get("rate", "+0%"),
            pitch=values.get("pitch", "+0Hz"),
        )


@dataclass(frozen=True, slots=True)
class Line:
    """One unit of narration: an id to hang it on, and the words."""

    id: str
    text: str

    @property
    def word_count(self) -> int:
        return count_words(self.text)


@dataclass(slots=True)
class Narration:
    """A measured track. `duration_sec` came from the file, not from the text."""

    scene_id: str
    voice: str
    rate: str
    pitch: str
    text: str
    word_count: int
    duration_sec: float
    sha256: str
    path: str
    cache_key: str
    cached: bool = False
    origin: str = SYNTHETIC

    @property
    def is_real_voice(self) -> bool:
        return self.origin == RECORDED

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class Synthesiser(Protocol):
    """Turns words into an audio file at a given path.

    A protocol, not a function, because this is the one place a film compile
    can invent a human being. Whoever supplies it has decided that inventing
    one is acceptable here, and `version` is what that decision is recorded as
    - it goes into the cache key, so changing synthesiser regenerates rather
    than silently reusing another voice's audio.
    """

    @property
    def version(self) -> str: ...

    def __call__(self, text: str, voice: Voice, destination: Path) -> None: ...


def measure(path: Path, *, runner: Runner | None = None) -> float:
    """Exact duration, probed. Never inferred from file size or word count."""
    call = runner or run
    # fmt: off
    argv = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    # fmt: on
    result = call(argv, timeout=60, check=True)
    text = result.stdout.strip()
    try:
        duration = float(text)
    except ValueError as exc:
        raise NarrationError(f"no duration for {path}: {text!r}") from exc
    if duration <= 0:
        raise NarrationError(f"zero-duration audio: {path}")
    return duration


def cache_key(text: str, voice: Voice, *, synth_version: str) -> str:
    """The content address of a synthesised line.

    Covers the words, the voice, the rate, the pitch and which synthesiser -
    so changing any of them regenerates and changing none of them costs
    nothing.
    """
    return stable_key(
        {
            "text": text,
            "voice": voice.name,
            "rate": voice.rate,
            "pitch": voice.pitch,
            "synth": synth_version,
        }
    )


@dataclass(slots=True)
class _Planned:
    line: Line
    key: str
    hit: bool


def adopt(
    line: Line,
    source: Path,
    *,
    workspace: Workspace,
    project: str,
    runner: Runner | None = None,
) -> Narration:
    """Take a real recording as it is, and measure it.

    Nothing is regenerated, re-encoded or trimmed: the file that arrives is the
    file that plays. Its content address is its own hash, because there is no
    request that would produce it again - a person said it once.
    """
    destination = workspace.artifact("audio", project) / f"{line.id}{source.suffix}"
    shutil.copy2(source, destination)
    digest = sha256_file(destination)
    return Narration(
        scene_id=line.id,
        voice=RECORDED,
        rate="+0%",
        pitch="+0Hz",
        text=line.text,
        word_count=line.word_count,
        duration_sec=round(measure(destination, runner=runner), 4),
        sha256=digest,
        path=str(destination),
        cache_key=digest,
        cached=False,
        origin=RECORDED,
    )


@dataclass(slots=True)
class Studio:
    """Synthesises a set of lines, reusing whatever it already has.

    The plan is decided - and reported - before any synthesis starts, so the
    report reads in line order even though a cold build synthesises several at
    once. Nothing about the result depends on the concurrency: the key is the
    content and the duration is measured afterwards.
    """

    workspace: Workspace
    synthesiser: Synthesiser
    runner: Runner | None = None
    reporter: Reporter = field(default_factory=Silent)

    def build(
        self,
        lines: list[Line],
        voice: Voice,
        *,
        project: str,
        offline: bool = False,
        workers: int = 1,
    ) -> tuple[list[Narration], dict[str, int]]:
        audio_dir = self.workspace.artifact("audio", project)
        store = self.workspace.store("tts")

        plan = [self._plan(line, voice, store) for line in lines]
        misses = [entry for entry in plan if not entry.hit]
        if misses and offline:
            raise NarrationError(
                "offline: no cached narration for "
                + ", ".join(f"{e.line.id} (key {e.key[:12]}...)" for e in misses)
                + ". Run once with access to the synthesiser to populate the store."
            )
        if misses:
            self._synthesise_all(misses, voice, audio_dir, store, workers)

        tracks = [self._collect(entry, voice, audio_dir, store) for entry in plan]
        hits = sum(1 for entry in plan if entry.hit)
        return tracks, {"hits": hits, "misses": len(misses)}

    def _plan(self, line: Line, voice: Voice, store: Path) -> _Planned:
        from . import cachestore

        key = cache_key(line.text, voice, synth_version=self.synthesiser.version)
        hit = (store / f"{key}.mp3").is_file() and (store / f"{key}.json").is_file()
        if hit:
            cachestore.touch(store / f"{key}.mp3")
        self.reporter.cache(
            HIT if hit else MISS,
            f"audio {line.id}" + ("" if hit else f" ({line.word_count} words)"),
        )
        return _Planned(line, key, hit)

    def _synthesise_all(
        self, misses: list[_Planned], voice: Voice, audio_dir: Path, store: Path, workers: int
    ) -> None:
        def one(entry: _Planned) -> None:
            destination = audio_dir / f"{entry.line.id}.mp3"
            self.synthesiser(entry.line.text, voice, destination)
            duration = measure(destination, runner=self.runner)
            atomic_copy(destination, store / f"{entry.key}.mp3")
            (store / f"{entry.key}.json").write_text(
                json.dumps({"duration_sec": duration, "key": entry.key}, indent=2)
            )

        lanes = max(1, min(workers, len(misses)))
        with ThreadPoolExecutor(max_workers=lanes) as pool:
            list(pool.map(one, misses))

    def _collect(self, entry: _Planned, voice: Voice, audio_dir: Path, store: Path) -> Narration:
        destination = audio_dir / f"{entry.line.id}.mp3"
        shutil.copy2(store / f"{entry.key}.mp3", destination)
        duration = json.loads((store / f"{entry.key}.json").read_text())["duration_sec"]
        track = Narration(
            scene_id=entry.line.id,
            voice=voice.name,
            rate=voice.rate,
            pitch=voice.pitch,
            text=entry.line.text,
            word_count=count_words(entry.line.text),
            duration_sec=round(duration, 4),
            sha256=sha256_file(destination),
            path=str(destination),
            cache_key=entry.key,
            cached=entry.hit,
            origin=SYNTHETIC,
        )
        (audio_dir / f"{entry.line.id}.json").write_text(json.dumps(track.to_json(), indent=2))
        return track
