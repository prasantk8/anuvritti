"""TASK-304 - the coverage gates are themselves part of the deliverable.

CLAUDE.md sets >= 90% unit and >= 80% integration. A threshold that is not wired into a
command nobody runs is a comment, so these tests assert the gate exists where CI reads it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text()


class TestGatesAreDeclared:
    def test_the_core_gate_covers_domain_and_application(self):
        assert "--cov=anuvritti.domain" in MAKEFILE
        assert "--cov=anuvritti.application" in MAKEFILE

    def test_the_core_gate_is_at_least_ninety_percent(self):
        core = MAKEFILE[MAKEFILE.index("cov-core:") : MAKEFILE.index("# CLAUDE.md: >= 80%")]
        threshold = int(core.split("--cov-fail-under=")[1].split()[0])
        assert threshold >= 90

    def test_the_overall_gate_is_at_least_eighty_percent(self):
        overall = MAKEFILE[MAKEFILE.index("\ncov:") :]
        threshold = int(overall.split("--cov-fail-under=")[1].split()[0])
        assert threshold >= 80

    #: `check` delegates to `_gates` under `make -k`, so one red gate no longer hides the
    #: rest. The guarantee being tested is unchanged: these gates run under `make check`.
    def _gate_list(self) -> str:
        return next(line for line in MAKEFILE.splitlines() if line.startswith("_gates:"))

    def test_check_delegates_to_the_gate_list_without_stopping_at_the_first_failure(self):
        check = next(line for line in MAKEFILE.splitlines() if line.startswith("\t@$(MAKE) -k"))
        assert "-k" in check
        assert "_gates" in check

    def test_check_runs_both_gates(self):
        gates = self._gate_list()
        assert "cov-core" in gates
        assert "cov" in gates

    def test_check_also_runs_lint_and_types(self):
        gates = self._gate_list()
        assert "lint" in gates
        assert "types" in gates


class TestCoverageMeasuresWhatItShould:
    def test_coverage_measures_branches_not_just_lines(self):
        import tomllib

        config = tomllib.loads((ROOT / "pyproject.toml").read_text())
        assert config["tool"]["coverage"]["run"]["branch"] is True

    def test_coverage_is_scoped_to_the_package(self):
        import tomllib

        config = tomllib.loads((ROOT / "pyproject.toml").read_text())
        assert config["tool"]["coverage"]["run"]["source"] == ["anuvritti"]

    @pytest.mark.parametrize(
        "suite",
        ["unit", "integration", "e2e", "constitution", "architecture", "foundation"],
    )
    def test_every_test_suite_exists_and_is_populated(self, suite: str):
        directory = ROOT / "tests" / suite
        assert directory.is_dir()
        assert list(directory.rglob("test_*.py")), f"tests/{suite} is empty"
