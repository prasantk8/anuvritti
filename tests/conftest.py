"""Fakes for the three things filmkit refuses to require: a shell, a voice, a browser."""

from __future__ import annotations

from pathlib import Path

import pytest

from filmkit.process import CommandResult
from filmkit.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.under(tmp_path)


class FakeRunner:
    """Records argv and answers with whatever the test says the tool said."""

    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout
        self.returncode = returncode
        self.on_call = None

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.on_call is not None:
            self.on_call(argv, kwargs)
        elif argv[0] == "ffmpeg":
            # A real encoder leaves a file behind, and the code under test copies
            # that file into the store. A fake that writes nothing would exercise
            # a path no build ever takes.
            Path(argv[-1]).write_bytes(b"encoded")
        return CommandResult(list(argv), self.returncode, self.stdout, "", 0.0)

    @property
    def last(self) -> list[str]:
        return self.calls[-1]

    def flat(self, index: int = -1) -> str:
        return " ".join(self.calls[index])


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


class FakeSynthesiser:
    """Writes bytes that stand in for a voice, and counts how often it was asked."""

    def __init__(self, version: str = "fake-1") -> None:
        self._version = version
        self.said: list[str] = []

    @property
    def version(self) -> str:
        return self._version

    def __call__(self, text, voice, destination) -> None:
        self.said.append(text)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"{voice.name}:{text}".encode())


@pytest.fixture
def synthesiser() -> FakeSynthesiser:
    return FakeSynthesiser()


class FakePainter:
    """Writes a PNG-shaped file per job, and remembers every document it saw."""

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.chunks: list[int] = []

    def __call__(self, width, height, jobs) -> None:
        self.chunks.append(len(jobs))
        for document, destination in jobs:
            self.documents.append(document)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"png:" + document.encode())


@pytest.fixture
def painter() -> FakePainter:
    return FakePainter()
