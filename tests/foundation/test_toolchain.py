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
