"""Measure voice bytes with ffprobe, without ever trusting the handset's timer."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from filmkit.narration import NarrationError, measure
from filmkit.process import CommandError, Runner

from anuvritti.shared.errors import DomainError, ErrorCode
from anuvritti.shared.result import Err, Ok, Result

_SUFFIX = {
    "audio/m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
}


class FfprobeAudioDurationMeasurer:
    """Decrypt-to-temp, probe, and remove; no family recording remains in plaintext."""

    def __init__(self, *, runner: Runner | None = None) -> None:
        self._runner = runner

    def measure(self, content: bytes, *, mime_type: str) -> Result[float, DomainError]:
        suffix = _SUFFIX.get(mime_type.split(";", 1)[0].strip().lower(), ".audio")
        descriptor, raw_path = tempfile.mkstemp(prefix="anuvritti-voice-", suffix=suffix)
        path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(content)
            return Ok(round(measure(path, runner=self._runner), 4))
        except (CommandError, NarrationError, OSError, ValueError) as exc:
            return Err(
                DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "the recording has no measurable audio duration",
                    {"reason": str(exc)},
                )
            )
        finally:
            path.unlink(missing_ok=True)
