#!/usr/bin/env python3
"""tracker.json protocol helper (CLAUDE.md 3).

Usage:
  tracker.py show [TASK-ID]
  tracker.py next
  tracker.py brief TASK-ID          # the task, its dependencies' files, what it unlocks
  tracker.py status TASK-ID
  tracker.py board                  # everything in flight, blocked, or landed with a commit
  tracker.py set TASK-ID {pending|in_progress|completed|blocked} [--files a.py,b.py] [--commit SHA]
  tracker.py validate

`brief` is where a chat starts: the task, what its dependencies left behind and what it
unlocks. tracker.json is 130 KB, so chats query it rather than open it whole. `board`
is the founder's view when several chats work at once, each recording itself with `set`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT / "tracker.json"
STATES = {"pending", "in_progress", "completed", "blocked"}


def load() -> dict:
    return json.loads(TRACKER.read_text())


def save(data: dict) -> None:
    TRACKER.write_text(json.dumps(data, indent=2) + "\n")


def all_tasks(data: dict):
    for phase in data["phases"]:
        for task in phase["tasks"]:
            yield phase, task


def find(data: dict, task_id: str) -> tuple[dict, dict] | None:
    for phase, task in all_tasks(data):
        if task["id"] == task_id:
            return phase, task
    return None


def cmd_validate(data: dict) -> int:
    ids = {t["id"] for _, t in all_tasks(data)}
    problems = []
    required = {
        "id",
        "description",
        "module_path",
        "verification_command",
        "dependencies",
        "status",
    }
    for _, task in all_tasks(data):
        missing = required - task.keys()
        if missing:
            problems.append(f"{task.get('id', '?')}: missing {sorted(missing)}")
        if task.get("status") not in STATES:
            problems.append(f"{task['id']}: bad status {task.get('status')!r}")
        for dep in task.get("dependencies", []):
            if dep not in ids:
                problems.append(f"{task['id']}: unknown dependency {dep}")
    for problem in problems:
        print(f"INVALID {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"tracker.json OK - {len(ids)} tasks, all dependencies resolve")
    return 0


def cmd_next(data: dict) -> int:
    done = {t["id"] for _, t in all_tasks(data) if t["status"] == "completed"}
    for _, task in all_tasks(data):
        if task["status"] == "pending" and all(d in done for d in task["dependencies"]):
            print(task["id"])
            return 0
    print("", end="")
    return 0


def cmd_show(data: dict, task_id: str | None) -> int:
    for _phase, task in all_tasks(data):
        if task_id in (None, task["id"]):
            flag = {"pending": " ", "in_progress": "~", "completed": "x", "blocked": "!"}[
                task["status"]
            ]
            print(f"[{flag}] {task['id']}  {task['description'][:88]}")
    return 0


def cmd_status(data: dict, task_id: str) -> int:
    found = find(data, task_id)
    if found is None:
        print(f"unknown task {task_id}", file=sys.stderr)
        return 1
    print(found[1]["status"])
    return 0


def cmd_brief(data: dict, task_id: str) -> int:
    """Print the one task, its dependencies' footprints, and what it unlocks."""
    found = find(data, task_id)
    if found is None:
        print(f"unknown task {task_id}", file=sys.stderr)
        return 1
    phase, task = found
    by_id = {t["id"]: t for _, t in all_tasks(data)}
    lines = [
        f"# {task['id']} - {phase['name']}",
        f"role: {task.get('role', '')}",
        f"status: {task['status']}",
        "",
        task["description"],
        "",
        f"module_path: {task['module_path']}",
        f"verification_command: {task['verification_command']}",
        f"prd_refs: {', '.join(task.get('prd_refs', [])) or '-'}",
    ]
    if task.get("note"):
        lines += ["", f"note: {task['note']}"]
    lines += ["", "## Depends on (already completed - read their changed_files, not the tracker)"]
    for dep_id in task["dependencies"]:
        dep = by_id[dep_id]
        lines.append(f"- {dep_id} [{dep['status']}] {dep['description'][:88]}")
        for path in dep.get("changed_files", [])[:12]:
            lines.append(f"    {path}")
    if not task["dependencies"]:
        lines.append("- none")
    unlocks = [t["id"] for _, t in all_tasks(data) if task_id in t["dependencies"]]
    lines += ["", f"## Unlocks: {', '.join(unlocks) or '-'}"]
    print("\n".join(lines))
    return 0


def cmd_board(data: dict) -> int:
    """Every task that is in flight, blocked, or landed with a recorded commit.

    This is the founder's view when several chats are working at once: each one records
    itself here with `set`, so one command answers "where is everything?".
    """
    groups: dict[str, list[str]] = {"in_progress": [], "blocked": [], "completed": []}
    for phase in data["phases"]:
        for task in phase["tasks"]:
            status = task["status"]
            if status in ("in_progress", "blocked") or (
                status == "completed" and task.get("commit")
            ):
                commit = f" @ {task['commit']}" if task.get("commit") else ""
                groups[status].append(f"  {task['id']}  {task['description'][:80]}{commit}")
    for status, lines in groups.items():
        if lines:
            print(f"{status}:")
            print("\n".join(lines))
    if not any(groups.values()):
        print("nothing in flight.")
    return 0


def cmd_set(data: dict, task_id: str, status: str, files: list[str], commit: str | None) -> int:
    if status not in STATES:
        print(f"bad status {status}", file=sys.stderr)
        return 1
    done = {t["id"] for _, t in all_tasks(data) if t["status"] == "completed"}
    for _, task in all_tasks(data):
        if task["id"] != task_id:
            continue
        if status == "in_progress":
            unmet = [d for d in task["dependencies"] if d not in done]
            if unmet:
                print(f"{task_id} blocked by unmet dependencies: {unmet}", file=sys.stderr)
                return 2
        task["status"] = status
        if files:
            task["changed_files"] = files
        if commit:
            task["commit"] = commit
        break
    else:
        print(f"unknown task {task_id}", file=sys.stderr)
        return 1

    data["completed_tasks"] = [t["id"] for _, t in all_tasks(data) if t["status"] == "completed"]
    data["blocked_tasks"] = [t["id"] for _, t in all_tasks(data) if t["status"] == "blocked"]
    for phase in data["phases"]:
        statuses = {t["status"] for t in phase["tasks"]}
        if statuses == {"completed"}:
            phase["status"] = "completed"
        elif "blocked" in statuses:
            phase["status"] = "blocked"
        elif statuses & {"in_progress", "completed"}:
            phase["status"] = "in_progress"
        else:
            phase["status"] = "pending"
    save(data)
    print(f"{task_id} -> {status}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    data = load()
    cmd = argv[0]
    if cmd == "validate":
        return cmd_validate(data)
    if cmd == "next":
        return cmd_next(data)
    if cmd == "board":
        return cmd_board(data)
    if cmd == "show":
        return cmd_show(data, argv[1] if len(argv) > 1 else None)
    if cmd in ("brief", "status") and len(argv) < 2:
        print(f"{cmd} needs a TASK-ID", file=sys.stderr)
        return 1
    if cmd == "brief":
        return cmd_brief(data, argv[1])
    if cmd == "status":
        return cmd_status(data, argv[1])
    if cmd == "set":
        files: list[str] = []
        commit: str | None = None
        if "--files" in argv:
            files = argv[argv.index("--files") + 1].split(",")
        if "--commit" in argv:
            commit = argv[argv.index("--commit") + 1]
        return cmd_set(data, argv[1], argv[2], files, commit)
    print(f"unknown command {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
