"""TASK-717 — duration comes from ffprobe and plaintext is ephemeral."""

from __future__ import annotations

from pathlib import Path

from filmkit.process import CommandResult

from anuvritti.adapters.media.measure import FfprobeAudioDurationMeasurer
from anuvritti.shared.errors import ErrorCode


class Probe:
    def __init__(self, answer: str = "2.375\n") -> None:
        self.answer = answer
        self.path: Path | None = None

    def __call__(self, argv, **_options):
        self.path = Path(argv[-1])
        assert self.path.read_bytes() == b"a family's voice"
        return CommandResult(list(argv), 0, self.answer, "", 0.01)


def test_ffprobe_measures_the_temporary_plaintext_and_it_is_removed():
    probe = Probe()
    measured = FfprobeAudioDurationMeasurer(runner=probe).measure(
        b"a family's voice", mime_type="audio/wav"
    )
    assert measured.unwrap() == 2.375
    assert probe.path is not None
    assert not probe.path.exists()


def test_an_unmeasurable_recording_is_an_expected_failure():
    measured = FfprobeAudioDurationMeasurer(runner=Probe("not-a-duration")).measure(
        b"a family's voice", mime_type="audio/wav"
    )
    assert measured.unwrap_err().code is ErrorCode.VALIDATION_FAILED
