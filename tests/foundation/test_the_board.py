"""The board is checked by `make check`, or it is checked by nobody.

`tracker.json` is the only record of where this product actually is, and for most of
Phase 9 it was wrong in a way no gate could see: twenty tasks stood closed on TASK-910,
a thirty-day validation gate that had never been run, and the document that was supposed
to close it had been written from test fixtures (docs/VALIDATION.md says so, at length).

`scripts/tracker.py` grew `validate` and `audit` in response. Neither ran anywhere. These
tests put the real board under the real suite, so drift in it fails the same way a type
error does.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACKER = ROOT / "tracker.json"


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "tracker.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_real_board_is_well_formed():
    """Every task has its fields, every dependency resolves, and no edge is a release gate."""
    result = _cli("validate")
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_task_depends_on_something_a_build_cannot_run():
    """A gate that needs a hand or a month is held in writing, never as an edge.

    This is the same rule `validate` enforces, asserted here against the real file so the
    failure message names the shape of the mistake rather than an exit code. TASK-910
    ("one family, thirty days") sat under all 57 tasks of Phases 10 to 14; TASK-907
    ("a real iPhone and a real Android, in a hand") sat under TASK-1004. A roadmap that
    cannot be built until somebody has lived a month gets resolved by writing down what
    the month would have said, which is exactly what happened.
    """
    board = json.loads(TRACKER.read_text())
    tasks = [task for phase in board["phases"] for task in phase["tasks"]]
    gates = {task["id"]: task["runs_on"] for task in tasks if task.get("runs_on")}
    assert gates, (
        "No task carries `runs_on`. TASK-907 and TASK-910 cannot be run by any build and "
        "must say so in the data, or this rule silently checks nothing."
    )
    edges = [
        f"{task['id']} -> {dep} (runs on {gates[dep]})"
        for task in tasks
        if not task.get("runs_on")
        for dep in task["dependencies"]
        if dep in gates
    ]
    assert not edges, (
        "A release gate is being used as a build dependency:\n  "
        + "\n  ".join(edges)
        + "\nHold it in docs/VALIDATION.md and let the work proceed."
    )


def test_a_deferred_gate_says_so_where_a_person_would_look():
    """The deferral lives in the document, not only in a note nobody opens.

    CLAUDE.md section 4: no document describes something that did not happen. The inverse
    is just as binding - a decision this large, taken on the board, has to be findable in
    the document the board points at.
    """
    board = json.loads(TRACKER.read_text())
    tasks = {t["id"]: t for phase in board["phases"] for t in phase["tasks"]}
    for task_id in (t for t, task in tasks.items() if task.get("runs_on")):
        document = ROOT / tasks[task_id]["module_path"]
        if document.suffix != ".md":
            continue
        text = document.read_text()
        assert "DEFERRED" in text or "NOT RUN" in text, (
            f"{document.relative_to(ROOT)} closes {task_id}, a gate no build can run, and "
            "says nothing about whether it has been run."
        )


def test_a_completed_task_names_a_file_that_exists():
    """ "Done" has to point at something. Five tasks pointed at nothing.

    `module_path` is the plan and `changed_files` is the record, and both drift: TASK-506
    was planned as `src/spark/SparkObject.tsx` and built as `src/components/Spark.tsx`,
    TASK-1102 recorded `shared/logging.py` in its `changed_files` beside the
    `config/logging.py` it actually wrote - a file it never created, listed as one it had.
    Five completed tasks named no path that existed anywhere on disk, so the board's own
    record of what they produced pointed into empty space.

    Open tasks are exempt: a task that has not run yet is *supposed* to name a file that
    does not exist. This asks only of the ones claiming to be finished.
    """
    board = json.loads(TRACKER.read_text())
    empty = []
    for phase in board["phases"]:
        for task in phase["tasks"]:
            if task["status"] != "completed":
                continue
            named = [task["module_path"], *task.get("changed_files", [])]
            if not any((ROOT / path).exists() for path in named):
                empty.append(f"{task['id']} -> {', '.join(named[:3]) or '(nothing named)'}")
    assert not empty, (
        "these tasks are completed and every path they name is missing from disk:\n  "
        + "\n  ".join(sorted(empty))
        + "\nRecord what the work actually produced with `tracker.py set --files`."
    )
