#!/usr/bin/env python3
"""tracker.json protocol helper (CLAUDE.md 3).

Usage:
  tracker.py show [TASK-ID]
  tracker.py next
  tracker.py set TASK-ID {pending|in_progress|completed|blocked} [--files a.py,b.py]
  tracker.py validate
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


def cmd_validate(data: dict) -> int:
    ids = {t["id"] for _, t in all_tasks(data)}
    problems = []
    required = {"id", "description", "module_path", "verification_command", "dependencies", "status"}
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
    for phase, task in all_tasks(data):
        if task_id in (None, task["id"]):
            flag = {"pending": " ", "in_progress": "~", "completed": "x", "blocked": "!"}[task["status"]]
            print(f"[{flag}] {task['id']}  {task['description'][:88]}")
    return 0


def cmd_set(data: dict, task_id: str, status: str, files: list[str]) -> int:
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
    if cmd == "show":
        return cmd_show(data, argv[1] if len(argv) > 1 else None)
    if cmd == "set":
        files: list[str] = []
        if "--files" in argv:
            files = argv[argv.index("--files") + 1].split(",")
        return cmd_set(data, argv[1], argv[2], files)
    print(f"unknown command {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
