"""The timing model, and the report that refuses to hide a conflict.

Three durations, kept apart on purpose:

    nominal    what the script's own timecodes asked for
    estimated  words / target WPM - a prediction, and never rendered
    actual     measured from the finished audio - the only one that renders

A script that does not fit its target is a fact about the script. The correct
response is to say so, in numbers, and render the honest length; the wrong ones
are to speed the voice up, to cut the tail off a sentence, or to quietly change
the target to whatever came out.

`visual_seconds` is where that is structural rather than stated. It takes a
beat and a measured duration, and there is no words-per-minute anywhere in its
arguments - so the function that decides how long something is on screen
cannot reach the estimate even by accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .narration import Narration

DEFAULT_LEAD_IN = 0.35
DEFAULT_TAIL = 0.55

BY_AUDIO = "audio"
BY_DURATION = "duration"

WITHIN = "WITHIN TOLERANCE"
CONFLICT = "TIMING CONFLICT"

SECONDS_PER_MINUTE = 60.0


@dataclass(frozen=True, slots=True)
class Beat:
    """One scene's timing intent, before anything has been measured."""

    id: str
    type: str
    mode: str = BY_AUDIO
    seconds: float | None = None
    min_sec: float = 0.0
    lead_in_sec: float = DEFAULT_LEAD_IN
    tail_sec: float = DEFAULT_TAIL
    nominal_start_sec: float | None = None
    wait_for: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode == BY_DURATION and self.seconds is None:
            raise ValueError(f"{self.id}: mode 'duration' with no seconds is not a duration")


def visual_seconds(beat: Beat, audio_sec: float) -> float:
    """How long this scene holds. Audio plus declared padding, floored.

    A declared `duration` is a floor, not a ceiling: it still has to hold the
    narration or the voice would be cut off mid-sentence, and shortening the
    picture is not a way to fix a script that runs long.
    """
    padded = audio_sec + beat.lead_in_sec + beat.tail_sec
    declared = beat.seconds if beat.mode == BY_DURATION and beat.seconds is not None else 0.0
    return max(padded, declared, beat.min_sec)


@dataclass(slots=True)
class SceneTiming:
    scene_id: str
    type: str
    words: int
    audio_sec: float
    lead_in_sec: float
    tail_sec: float
    visual_sec: float
    start_sec: float
    end_sec: float
    nominal_start_sec: float | None
    nominal_drift_sec: float | None
    estimated_sec: float
    mode: str
    wait_for: list[str]
    reason: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TimingReport:
    scenes: list[SceneTiming] = field(default_factory=list)
    total_words: int = 0
    target_wpm: float = 150.0
    estimated_sec: float = 0.0
    target_sec: float = 0.0
    actual_sec: float = 0.0
    tolerance_sec: float = 0.0

    @property
    def delta_vs_target(self) -> float:
        return self.actual_sec - self.target_sec

    @property
    def delta_estimate_vs_actual(self) -> float:
        return self.actual_sec - self.estimated_sec

    @property
    def conflict(self) -> bool:
        return abs(self.delta_vs_target) > self.tolerance_sec

    @property
    def status(self) -> str:
        return CONFLICT if self.conflict else WITHIN

    @property
    def effective_wpm(self) -> float:
        """Words per minute of finished film, from measured durations.

        Not the target, which is a wish, and not words over pure speech time:
        the denominator is the whole scene, padding included, because that is
        the pace a viewer actually experiences. The gap between this number
        and the target is the entire reason this report exists.
        """
        return self.total_words / (self.actual_sec / SECONDS_PER_MINUTE) if self.actual_sec else 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "total_words": self.total_words,
            "target_wpm": self.target_wpm,
            "estimated_duration_sec": round(self.estimated_sec, 3),
            "target_duration_sec": round(self.target_sec, 3),
            "actual_duration_sec": round(self.actual_sec, 3),
            "delta_vs_target_sec": round(self.delta_vs_target, 3),
            "delta_estimate_vs_actual_sec": round(self.delta_estimate_vs_actual, 3),
            "effective_wpm": round(self.effective_wpm, 2) if self.actual_sec else 0.0,
            "tolerance_sec": self.tolerance_sec,
            "status": self.status,
            "scenes": [scene.to_json() for scene in self.scenes],
        }

    def render_text(self) -> str:
        lines = [
            "Narration preflight",
            "-------------------",
            f"word count:           {self.total_words}",
            f"target WPM:           {self.target_wpm:.0f}",
            f"estimated duration:   {self.estimated_sec:6.1f} sec   (word count / target WPM)",
            f"actual duration:      {self.actual_sec:6.1f} sec   (measured)",
            f"target duration:      {self.target_sec:6.1f} sec   (script's nominal length)",
            f"delta vs target:      {self.delta_vs_target:+6.1f} sec",
            f"effective WPM:        {self.effective_wpm:6.1f}"
            if self.actual_sec
            else "effective WPM:            n/a",
            f"tolerance:            {self.tolerance_sec:6.1f} sec",
            "",
            f"STATUS: {self.status}",
            "",
            "Per scene",
            "---------",
            f"{'scene':<22}{'words':>6}{'audio':>9}{'visual':>9}{'start':>9}"
            f"{'nominal':>9}{'drift':>8}  mode",
        ]
        for scene in self.scenes:
            nominal = (
                f"{scene.nominal_start_sec:8.1f}"
                if scene.nominal_start_sec is not None
                else "       -"
            )
            drift = (
                f"{scene.nominal_drift_sec:+7.1f}"
                if scene.nominal_drift_sec is not None
                else "      -"
            )
            lines.append(
                f"{scene.scene_id:<22}{scene.words:>6}{scene.audio_sec:>9.2f}"
                f"{scene.visual_sec:>9.2f}{scene.start_sec:>9.2f}{nominal}{drift}  {scene.mode}"
            )
        return "\n".join(lines)


def plan(
    beats: list[Beat],
    tracks: list[Narration],
    *,
    target_wpm: float,
    target_sec: float,
    tolerance_sec: float,
) -> TimingReport:
    """Lay the beats end to end against their measured audio."""
    by_id = {track.scene_id: track for track in tracks}
    scenes: list[SceneTiming] = []
    cursor = 0.0

    for beat in beats:
        track = by_id[beat.id]
        visual = visual_seconds(beat, track.duration_sec)
        nominal = beat.nominal_start_sec
        scenes.append(
            SceneTiming(
                scene_id=beat.id,
                type=beat.type,
                words=track.word_count,
                audio_sec=round(track.duration_sec, 3),
                lead_in_sec=beat.lead_in_sec,
                tail_sec=beat.tail_sec,
                visual_sec=round(visual, 3),
                start_sec=round(cursor, 3),
                end_sec=round(cursor + visual, 3),
                nominal_start_sec=nominal,
                nominal_drift_sec=round(cursor - nominal, 3) if nominal is not None else None,
                estimated_sec=round(track.word_count / target_wpm * SECONDS_PER_MINUTE, 3),
                mode=beat.mode,
                wait_for=list(beat.wait_for),
                reason=beat.reason,
            )
        )
        cursor += visual

    total_words = sum(scene.words for scene in scenes)
    return TimingReport(
        scenes=scenes,
        total_words=total_words,
        target_wpm=target_wpm,
        estimated_sec=total_words / target_wpm * SECONDS_PER_MINUTE,
        target_sec=target_sec,
        actual_sec=cursor,
        tolerance_sec=tolerance_sec,
    )
