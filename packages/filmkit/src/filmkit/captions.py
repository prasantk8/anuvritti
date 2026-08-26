"""Captions, generated from the same words the voice said.

There is no hand-authored subtitle track and no place to put one. A caption is
a view of the narration already in the timeline, which is the only arrangement
where the two cannot drift apart.

A cue starts when its scene's audio starts and ends when the audio ends. The
lead-in and tail are silence, so captioning them would put words on screen over
nothing - and a viewer reading a sentence that nobody is saying is a small lie
told sixty times a film.
"""

from __future__ import annotations

from pathlib import Path

from .timeline import Timeline

SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
MILLIS = 1000


def _clock(seconds: float, comma: bool) -> str:
    hours, rest = divmod(max(0.0, seconds), SECONDS_PER_HOUR)
    minutes, secs = divmod(rest, SECONDS_PER_MINUTE)
    whole = int(secs)
    millis = round((secs - whole) * MILLIS)
    if millis == MILLIS:
        whole, millis = whole + 1, 0
    separator = "," if comma else "."
    return f"{int(hours):02d}:{int(minutes):02d}:{whole:02d}{separator}{millis:03d}"


def cues(timeline: Timeline) -> list[tuple[float, float, str]]:
    """(start, end, text) per scene, in film time.

    The silence is assumed to sit evenly either side of the speech, which is
    what the timing model produces and what a caption can honestly claim
    without measuring the waveform.
    """
    found = []
    cursor = 0.0
    for scene in timeline.scenes:
        lead_in = max(0.0, (scene.visual_duration_sec - scene.audio_duration_sec) / 2)
        start = cursor + lead_in
        found.append((start, start + scene.audio_duration_sec, scene.narration))
        cursor += scene.visual_duration_sec
    return found


def write_srt(timeline: Timeline, path: Path) -> Path:
    blocks = [
        f"{index}\n{_clock(start, True)} --> {_clock(end, True)}\n{text}\n"
        for index, (start, end, text) in enumerate(cues(timeline), start=1)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def write_vtt(timeline: Timeline, path: Path) -> Path:
    blocks = ["WEBVTT\n"]
    blocks += [
        f"{_clock(start, False)} --> {_clock(end, False)}\n{text}\n"
        for start, end, text in cues(timeline)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path
