"""Every module can be reached from something that runs.

The Phase 5 pairing bug was correct code, fully tested, that no route could reach. The
route graph test was written so that could not happen to a *route* again. It happened
again at module scale: Phases 9-11 landed eleven modules that nothing constructs, and
every one of them passed its own tests, because a test is a caller and the test suite is
not production.

So this is the same guard one level up. Walk the import graph out from the things that
actually start - the ASGI app, the operational scripts - and any module the walk does not
reach has to say so out loud in `NOT_IN_SERVICE` with a reason and an open task. A module
may be unfinished. It may not be quietly unfinished.

Adding a name here is a deliberate act with a task id attached. Deleting one is the
definition of "wired". The list only ever shrinks.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "anuvritti"
APP = ROOT / "apps" / "anuvritti"

# ---------------------------------------------------------------- python

#: What actually starts. `asgi` is the process uvicorn boots; the scripts are the
#: operational surface an on-call parent-of-one runs at 3am.
PY_ENTRY_POINTS = (
    "anuvritti.interfaces.http.asgi",
    "anuvritti.config.settings",
)

#: Every front door this repository has that is not the ASGI app. They are *found*, not
#: listed: `scripts/*.py` are parsed for their imports, and the Makefile is read for
#: `python -m anuvritti.…`, because a hand-maintained list is a second place to remember
#: and it always falls behind. It did not know about `rotate_keys.py` or
#: `retention_cron.py` (TASK-1107, TASK-1108), which is why `observability.slo` read as an
#: orphan while `scripts/release.py` was importing it.
SCRIPTS = ROOT / "scripts"
MAKEFILE = ROOT / "Makefile"

_MAKE_MODULE = re.compile(r"-m\s+(anuvritti(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")

#: The one thing neither parser can see: `backup.sh` and `restore.sh` embed their Python
#: in a `python3 -c` heredoc, so the module they import has to be named here.
PY_SCRIPT_IMPORTS = ("anuvritti.adapters.backup",)

#: Reached by nothing that runs. Each line is a debt with an owner, not an exemption.
NOT_IN_SERVICE: dict[str, str] = {
    "anuvritti.application.import_": "TASK-1102 - importer has no CLI and no route",
    "anuvritti.adapters.persistence.inbox": (
        "TASK-806 - the Future Inbox store is built and the container does not hold it"
    ),
    "anuvritti.adapters.persistence.migrations": "TASK-1101 - container calls schema.migrate()",
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _all_python_modules() -> dict[str, Path]:
    return {
        _module_name(p): p
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py"
    }


def _imports_of(path: Path) -> set[str]:
    """Every `anuvritti.*` name this file imports, including `from x import y` members."""
    found: set[str] = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("anuvritti"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if not node.module.startswith("anuvritti"):
                continue
            found.add(node.module)
            # `from anuvritti.adapters import backup` names a module, not an attribute.
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _reachable_python() -> set[str]:
    modules = _all_python_modules()
    seen: set[str] = set()
    queue = [*PY_ENTRY_POINTS, *PY_SCRIPT_IMPORTS]
    for script in sorted(SCRIPTS.glob("*.py")):
        queue.extend(_imports_of(script))
    queue.extend(_MAKE_MODULE.findall(MAKEFILE.read_text()))
    while queue:
        name = queue.pop()
        if name in seen or name not in modules:
            continue
        seen.add(name)
        queue.extend(_imports_of(modules[name]))
    return seen


def test_every_python_module_is_reached_or_declared():
    modules = set(_all_python_modules())
    orphans = modules - _reachable_python() - set(NOT_IN_SERVICE)
    assert not orphans, (
        "these modules are reached by nothing that runs, and do not say so:\n  "
        + "\n  ".join(sorted(orphans))
        + "\nWire them, delete them, or add them to NOT_IN_SERVICE with the open task id."
    )


def test_nothing_declared_out_of_service_is_actually_wired():
    """The list only shrinks. A module that got wired must lose its excuse."""
    still_dark = set(NOT_IN_SERVICE) - _reachable_python()
    now_wired = set(NOT_IN_SERVICE) - still_dark
    assert not now_wired, (
        "these are wired now - delete them from NOT_IN_SERVICE:\n  "
        + "\n  ".join(sorted(now_wired))
    )


def test_every_excuse_names_a_task():
    for module, reason in (*NOT_IN_SERVICE.items(), *TS_NOT_IN_SERVICE.items()):
        assert re.match(r"TASK-\d+", reason), f"{module}: '{reason}' names no task"


def test_every_excuse_names_a_task_that_is_still_open():
    """An excuse is a debt. A debt whose task is closed is a lie the board is telling.

    `docs/AGENT-GUIDE.md` section 2 says a module the walk cannot reach must name "a reason
    and an *open* task id". Nothing checked the second half, and the board drifted until
    nine excuses here pointed at tasks marked `completed` - the module unreachable, the
    task done, and `tracker.py audit` reporting "board OK" because it only ever compared
    tasks to each other. Two records of the same fact disagreeing is exactly what a
    fitness function is for.
    """
    board = json.loads((ROOT / "tracker.json").read_text())
    status = {task["id"]: task["status"] for phase in board["phases"] for task in phase["tasks"]}
    closed = {
        f"{module} -> {reason}"
        for module, reason in (*NOT_IN_SERVICE.items(), *TS_NOT_IN_SERVICE.items())
        if status.get(re.match(r"TASK-\d+", reason).group(0)) == "completed"  # type: ignore[union-attr]
    }
    assert not closed, (
        "these modules are out of service and the task that would wire them is closed:\n  "
        + "\n  ".join(sorted(closed))
        + "\nReopen the task, or wire the module and delete its line."
    )


# ---------------------------------------------------------------- typescript

#: Expo Router turns every file under `app/` into a screen. That is the entry set.
TS_ENTRY_GLOB = "app/**/*.tsx"

#: The app's own source that no screen reaches. Same rule, same shrinking list.
TS_NOT_IN_SERVICE: dict[str, str] = {
    "src/capture/native.ts": "TASK-1002 - in-app camera has no screen",
    "src/model/today.ts": "TASK-1008 - papaToday has no screen",
    "src/return/notifications.ts": "TASK-1004 - no screen registers the scheduler",
    "src/sync/budget.ts": "TASK-1003 - metering has no caller",
    "src/sync/uploader.ts": "TASK-1002 - resumable upload has no caller",
    "src/vault/device-vault.ts": "TASK-1005 - reachable only from capture/native.ts",
    "src/widgets/index.ts": "TASK-1009 - barrel over the widget",
    "src/widgets/right-now-widget.ts": "TASK-1009 - no native widget extension consumes it",
}

_TS_IMPORT = re.compile(r"""from\s+["'](\.[^"']+)["']""")


def _ts_resolve(importer: Path, spec: str) -> Path | None:
    target = (importer.parent / spec).resolve()
    for candidate in (target, target.with_suffix(".ts"), target.with_suffix(".tsx")):
        if candidate.is_file():
            return candidate
    for suffix in ("index.ts", "index.tsx"):
        if (target / suffix).is_file():
            return target / suffix
    return None


def _reachable_ts() -> set[str]:
    queue = list(APP.glob(TS_ENTRY_GLOB))
    seen: set[Path] = set()
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for spec in _TS_IMPORT.findall(path.read_text()):
            resolved = _ts_resolve(path, spec)
            if resolved is not None:
                queue.append(resolved)
    return {p.relative_to(APP).as_posix() for p in seen}


def test_every_app_module_is_reached_or_declared():
    on_disk = {
        p.relative_to(APP).as_posix()
        for p in (APP / "src").rglob("*.ts*")
        if "node_modules" not in p.parts
    }
    orphans = on_disk - _reachable_ts() - set(TS_NOT_IN_SERVICE)
    assert not orphans, (
        "no screen reaches these, and they do not say so:\n  "
        + "\n  ".join(sorted(orphans))
        + "\nRender them, delete them, or add them to TS_NOT_IN_SERVICE with the task id."
    )


def test_nothing_declared_dark_is_actually_rendered():
    now_wired = set(TS_NOT_IN_SERVICE) & _reachable_ts()
    assert not now_wired, (
        "a screen reaches these now - delete them from TS_NOT_IN_SERVICE:\n  "
        + "\n  ".join(sorted(now_wired))
    )
