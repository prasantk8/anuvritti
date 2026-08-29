"""TASK-101 - the toolchain itself is a deliverable, so it is tested."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_package_is_importable_from_src_layout():
    import anuvritti  # noqa: F401


def test_python_floor_is_312():
    assert _pyproject()["project"]["requires-python"] == ">=3.12"


def test_pytest_finds_src_without_installation():
    assert _pyproject()["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]


def test_warnings_are_errors():
    """A DeprecationWarning in a family archive is a future data-loss bug."""
    assert "error" in _pyproject()["tool"]["pytest"]["ini_options"]["filterwarnings"]


def test_mypy_is_strict():
    assert _pyproject()["tool"]["mypy"]["strict"] is True


def test_coverage_measures_branches():
    assert _pyproject()["tool"]["coverage"]["run"]["branch"] is True


def test_ruff_enforces_security_lints():
    assert "S" in _pyproject()["tool"]["ruff"]["lint"]["select"]


def test_no_secrets_committed():
    """PRD 44 - zero secrets in the repository."""
    assert not (ROOT / ".env").exists(), ".env must never be committed"
    example = (ROOT / ".env.example").read_text()
    assert "BEGIN PRIVATE KEY" not in example


def test_declared_runtime_dependencies_are_minimal():
    """Every runtime dependency is a supply-chain liability for family data."""
    deps = _pyproject()["project"]["dependencies"]
    assert len(deps) <= 6, f"runtime dependency creep: {deps}"


def test_make_install_installs_the_project_itself():
    """`make run` needs the package on sys.path; only pytest was ever given it.

    `pythonpath = ["src"]` above is a pytest setting, so the suite imported
    `anuvritti` happily for eleven phases while `make run` - plain uvicorn,
    reading plain sys.path - died with ModuleNotFoundError. The container was
    always fine, which is what hid it: the Dockerfile runs `pip install .`. The
    half that broke was the fallback docs/CONTINUITY.md offers to a parent whose
    Docker install has failed, which is the worst possible half to have broken.
    """
    dev = (ROOT / "requirements-dev.txt").read_text().splitlines()
    installs_self = [ln for ln in dev if ln.strip() in {"-e .", "."}]
    assert installs_self, (
        "requirements-dev.txt does not install the project, so `make install` "
        "leaves `make run` unable to import anuvritti"
    )


def test_the_command_continuity_promises_names_a_real_module():
    """docs/CONTINUITY.md is read on the worst day. Its commands have to run.

    Item 6 tells a parent to start the archive with `make run`. That expands to a
    uvicorn invocation naming an import path, and nothing but this test checks
    that the path still resolves to something that exists.
    """
    import importlib
    import re

    makefile = (ROOT / "Makefile").read_text()
    target = re.search(r"^run:\n\t.*uvicorn\s+(\S+):(\S+)", makefile, re.M)
    assert target, "Makefile has no `run` target invoking uvicorn"
    module, attribute = target.group(1), target.group(2)

    assert (ROOT / "docs" / "CONTINUITY.md").read_text().count("make run") >= 1
    assert hasattr(importlib.import_module(module), attribute)
