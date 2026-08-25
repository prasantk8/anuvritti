"""TASK-513 - the golden path, end to end, across both languages.

`test_golden_path.py` drives the server directly with `TestClient`. That proves the server
implements PRD 48, and it cannot prove the phone does: it never opens a socket, never
serialises a real request, and never exercises a line of the client that the app depends on.

This does. It starts the real ASGI application on a real port and runs the real generated
TypeScript client against it, in the real Node runtime the app ships. Everything between the
two is genuine - JSON on the wire, bearer tokens in headers, idempotency keys, the
offline queue holding a capture and replaying it.

The clock is the one thing held: the server's `FrozenClock` lives in this process, so the
test can let eight months pass between the two halves of the story. That is the only way to
write this test without waiting until September.

What this still does not cover is the view layer, which needs a device. `docs/DEVICE.md` is
that checklist, and it is short precisely because everything checkable off a device is here.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn
from cryptography.fernet import Fernet

from anuvritti.config.settings import load_settings
from anuvritti.interfaces.http.app import create_app
from anuvritti.interfaces.http.container import build_container
from anuvritti.shared.clock import FrozenClock
from anuvritti.shared.identity import FamilyId, SequentialIdGenerator

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packages" / "client" / "test" / "e2e" / "golden-path.ts"

#: A Tuesday evening in January. He is putting the child to bed and scrolling.
JANUARY = datetime(2026, 1, 13, 21, 40, tzinfo=UTC)

#: Eight months, landing on a Saturday in September.
EIGHT_MONTHS = 243

_STARTUP_TIMEOUT_SECONDS = 15.0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class RunningServer:
    """The real application, on a real port, with a clock this process can move."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = FrozenClock(JANUARY)
        self.port = _free_port()
        settings = load_settings(
            {
                "ANUVRITTI_ENV": "test",
                "ANUVRITTI_DB_PATH": str(tmp_path / "device.db"),
                "ANUVRITTI_MEDIA_DIR": str(tmp_path / "media"),
                "ANUVRITTI_MEDIA_KEY": Fernet.generate_key().decode(),
            }
        ).unwrap()
        self.container = build_container(
            settings, clock=self.clock, ids=SequentialIdGenerator("id")
        )
        app = create_app(settings, container=self.container)
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("the server did not start")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)
        self.container.close()


@pytest.fixture
def server(tmp_path: Path):
    running = RunningServer(tmp_path)
    running.start()
    yield running
    running.stop()


def _run_phase(phase: str, server: RunningServer, state_file: Path) -> str:
    """Run one half of the story in Node, and fail loudly with its own output."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["node", str(SCRIPT), phase, server.base_url, str(state_file)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=ROOT,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"the {phase} half of the golden path failed\n"
            f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
        )
    return completed.stdout


class TestTheWholeProductThroughTheClientTheAppShips:
    def test_a_reel_in_january_becomes_a_saturday_in_september(self, server, tmp_path, capsys):
        state = tmp_path / "phone-state.json"

        january = _run_phase("january", server, state)
        assert "paired" in january
        assert "saved to the queue with no network" in january
        assert "replay produced no duplicate" in january

        # Eight months. The phone is closed the whole time; only its keychain survives,
        # which is exactly what the state file holds.
        server.clock.advance(days=EIGHT_MONTHS)

        september = _run_phase("september", server, state)
        assert "brought back" in september
        assert "lived" in september
        assert "exported, and it is all there" in september

        with capsys.disabled():
            print(f"\n{january}{september}")

    def test_the_phone_ended_up_with_exactly_one_paired_device(self, server, tmp_path):
        """Bootstrap pairs one device. Nothing in the story should have created another."""
        state = tmp_path / "phone-state.json"
        _run_phase("january", server, state)

        paired = json.loads(state.read_text())
        devices = server.container.devices.list_for_family(FamilyId(paired["familyId"])).unwrap()

        assert len(devices) == 1
        assert devices[0].display_name == "This device"
        assert not devices[0].is_revoked

    def test_the_server_stored_no_token_it_could_replay(self, server, tmp_path):
        """The strongest statement this test can make about the pairing design.

        The phone is holding a working token. The server, having issued it, holds only a
        SHA-256 fingerprint - so a stolen copy of the archive cannot be used to make a
        request, which is the whole reason the archive is a single portable file.
        """
        state = tmp_path / "phone-state.json"
        _run_phase("january", server, state)
        token = json.loads(state.read_text())["token"]

        rows = server.container.connection.execute("SELECT * FROM device").fetchall()
        assert rows
        for row in rows:
            stored = " ".join(str(value) for value in tuple(row))
            assert token not in stored, "the plaintext token reached the database"
