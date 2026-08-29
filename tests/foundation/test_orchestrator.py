"""TASK-105 - the orchestrator is production code and is tested like it.

It drives every other task, so a silent bug in it means silently doing nothing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "orchestrate.sh"
TRACKER_CLI = ROOT / "scripts" / "tracker.py"


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the copy of tracker.py that lives inside `cwd`.

    tracker.py deliberately resolves its own project root from `__file__`, so the sandbox
    must exercise its own copy rather than the real project's.
    """
    return subprocess.run(  # noqa: S603
        [sys.executable, str(cwd / "scripts" / "tracker.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A throwaway project root with its own tracker.json."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(TRACKER_CLI, tmp_path / "scripts" / "tracker.py")
    return tmp_path


def _write_tracker(root: Path, tasks: list[dict], phase: str = "Phase 1: Foundations") -> None:
    (root / "tracker.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "phases": [{"name": phase, "owner": "x", "status": "pending", "tasks": tasks}],
                "completed_tasks": [],
                "blocked_tasks": [],
            }
        )
    )


def _task(task_id: str, deps: list[str] | None = None, status: str = "pending") -> dict:
    return {
        "id": task_id,
        "description": "d",
        "module_path": "m",
        "verification_command": "true",
        "dependencies": deps or [],
        "status": status,
    }


class TestShellScript:
    def test_script_is_syntactically_valid(self):
        assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0  # noqa: S603, S607

    def test_script_is_executable(self):
        assert SCRIPT.stat().st_mode & 0o111

    def test_uses_strict_mode(self):
        assert "set -euo pipefail" in SCRIPT.read_text()

    def test_does_not_iterate_unquoted_jq_output(self):
        """The original bug: `for phase in $(jq -r '.phases[].name')` word-splits.

        A phase named "Phase 1: Foundations" became three phantom phases and the task
        loop matched nothing, so the orchestrator reported success having done nothing.
        """
        source = SCRIPT.read_text()
        assert "for phase in $(jq" not in source
        assert "for task_id in $task_ids" not in source

    def test_task_selection_is_delegated_to_the_tested_helper(self):
        assert "$TRACKER_CLI next" in SCRIPT.read_text()

    def test_validates_the_tracker_before_running(self):
        assert "validate" in SCRIPT.read_text()

    def test_runs_the_task_specific_verification_command(self):
        assert "verification_command" in SCRIPT.read_text()

    def test_verification_is_not_delegated_to_the_model(self):
        """Step C must run the tests itself, never take the model's word for it."""
        assert "run_verification" in SCRIPT.read_text()

    def test_records_changed_files_on_completion(self):
        assert "changed_files_since" in SCRIPT.read_text()


class TestDependencyGating:
    def test_next_returns_the_first_unblocked_task(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1"), _task("TASK-2", ["TASK-1"])])
        assert _run_cli(sandbox, "next").stdout.strip() == "TASK-1"

    def test_next_skips_tasks_whose_dependencies_are_unmet(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1", status="blocked"), _task("TASK-2", ["TASK-1"])])
        assert _run_cli(sandbox, "next").stdout.strip() == ""

    def test_next_unblocks_once_the_dependency_completes(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1"), _task("TASK-2", ["TASK-1"])])
        _run_cli(sandbox, "set", "TASK-1", "completed")
        assert _run_cli(sandbox, "next").stdout.strip() == "TASK-2"

    def test_cannot_start_a_task_with_unmet_dependencies(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1"), _task("TASK-2", ["TASK-1"])])
        result = _run_cli(sandbox, "set", "TASK-2", "in_progress")
        assert result.returncode == 2
        assert "unmet dependencies" in result.stderr

    def test_next_is_empty_when_everything_is_done(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1", status="completed")])
        assert _run_cli(sandbox, "next").stdout.strip() == ""


class TestTrackerProtocol:
    def test_phase_names_containing_spaces_are_handled(self, sandbox: Path):
        """The exact shape that broke the original loop."""
        _write_tracker(sandbox, [_task("TASK-1")], phase="Phase 1: Foundations")
        assert _run_cli(sandbox, "next").stdout.strip() == "TASK-1"

    def test_completion_updates_the_rollup_lists(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1"), _task("TASK-2")])
        _run_cli(sandbox, "set", "TASK-1", "completed")
        data = json.loads((sandbox / "tracker.json").read_text())
        assert data["completed_tasks"] == ["TASK-1"]

    def test_phase_status_becomes_completed_when_all_tasks_are(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        _run_cli(sandbox, "set", "TASK-1", "completed")
        data = json.loads((sandbox / "tracker.json").read_text())
        assert data["phases"][0]["status"] == "completed"

    def test_phase_status_becomes_blocked_when_a_task_is(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1"), _task("TASK-2")])
        _run_cli(sandbox, "set", "TASK-1", "blocked")
        data = json.loads((sandbox / "tracker.json").read_text())
        assert data["phases"][0]["status"] == "blocked"

    def test_changed_files_are_recorded(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        _run_cli(sandbox, "set", "TASK-1", "completed", "--files", "a.py,b.py")
        data = json.loads((sandbox / "tracker.json").read_text())
        assert data["phases"][0]["tasks"][0]["changed_files"] == ["a.py", "b.py"]

    def test_unknown_status_is_rejected(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        assert _run_cli(sandbox, "set", "TASK-1", "almost_done").returncode == 1

    def test_unknown_task_is_rejected(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        assert _run_cli(sandbox, "set", "TASK-9", "completed").returncode == 1

    def test_validate_detects_a_dangling_dependency(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1", ["TASK-NOPE"])])
        result = _run_cli(sandbox, "validate")
        assert result.returncode == 1
        assert "unknown dependency" in result.stderr

    def test_validate_detects_a_missing_required_field(self, sandbox: Path):
        broken = _task("TASK-1")
        del broken["verification_command"]
        _write_tracker(sandbox, [broken])
        assert _run_cli(sandbox, "validate").returncode == 1

    def test_audit_catches_a_task_finished_on_an_open_gate(self, sandbox: Path):
        """The Phase 10/11 failure, in miniature.

        Twenty tasks closed on TASK-910 while TASK-910 had never been run. `validate` is
        blind to it - the file is perfectly well formed - so the question gets its own
        command.
        """
        _write_tracker(
            sandbox,
            [_task("GATE"), _task("TASK-1", ["GATE"], status="completed")],
        )
        assert _run_cli(sandbox, "validate").returncode == 0

        result = _run_cli(sandbox, "audit")
        assert result.returncode == 1
        assert "TASK-1" in result.stderr
        assert "GATE" in result.stderr

    def test_audit_passes_when_every_finished_task_stands_on_finished_work(self, sandbox: Path):
        _write_tracker(
            sandbox,
            [_task("GATE", status="completed"), _task("TASK-1", ["GATE"], status="completed")],
        )
        assert _run_cli(sandbox, "audit").returncode == 0

    def test_a_note_records_why_a_task_moved(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1", status="completed")])
        _run_cli(sandbox, "set", "TASK-1", "pending", "--note", "reopened: the claim was untrue")
        data = json.loads((sandbox / "tracker.json").read_text())
        assert data["phases"][0]["tasks"][0]["note"] == "reopened: the claim was untrue"


class TestRealTracker:
    def test_the_projects_own_tracker_is_valid(self):
        assert _run_cli(ROOT, "validate").returncode == 0

    def test_every_task_has_a_role_and_prd_reference(self):
        data = json.loads((ROOT / "tracker.json").read_text())
        for phase in data["phases"]:
            for task in phase["tasks"]:
                assert task.get("role"), f"{task['id']} has no role"
                assert task.get("prd_refs"), f"{task['id']} has no PRD reference"


# --- tracker.py brief / status / --commit --------------------------------------------


class TestBrief:
    def test_brief_shows_the_task_and_its_dependencies_footprint(self, sandbox: Path):
        first = _task("TASK-1", status="completed") | {"changed_files": ["src/a.py"]}
        _write_tracker(sandbox, [first, _task("TASK-2", ["TASK-1"]), _task("TASK-3", ["TASK-2"])])
        out = _run_cli(sandbox, "brief", "TASK-2").stdout
        assert "# TASK-2 - Phase 1: Foundations" in out
        assert "TASK-1 [completed]" in out
        assert "src/a.py" in out
        assert "Unlocks: TASK-3" in out

    def test_brief_of_an_unknown_task_fails(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        assert _run_cli(sandbox, "brief", "TASK-9").returncode == 1

    def test_status_prints_the_status(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1", status="blocked")])
        assert _run_cli(sandbox, "status", "TASK-1").stdout.strip() == "blocked"

    def test_commit_hash_is_recorded(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        _run_cli(sandbox, "set", "TASK-1", "completed", "--commit", "abc1234")
        data = json.loads((sandbox / "tracker.json").read_text())
        assert data["phases"][0]["tasks"][0]["commit"] == "abc1234"

    def test_board_lists_what_is_in_flight(self, sandbox: Path):
        landed = _task("TASK-1", status="completed") | {"commit": "abc1234"}
        _write_tracker(
            sandbox,
            [
                landed,
                _task("TASK-2", status="in_progress"),
                _task("TASK-3", status="blocked"),
                _task("TASK-4"),
            ],
        )
        out = _run_cli(sandbox, "board").stdout
        assert "in_progress:" in out and "TASK-2" in out
        assert "blocked:" in out and "TASK-3" in out
        assert "completed:" in out and "TASK-1" in out and "@ abc1234" in out
        assert "TASK-4" not in out

    def test_board_is_quiet_when_nothing_is_in_flight(self, sandbox: Path):
        _write_tracker(sandbox, [_task("TASK-1")])
        assert "nothing in flight" in _run_cli(sandbox, "board").stdout
