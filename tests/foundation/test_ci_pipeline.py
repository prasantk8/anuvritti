"""TASK-403 - CI is the only thing that actually enforces any of this.

Every gate this project claims to have exists because a CI job runs it. If a job is
deleted, this test fails, which is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
RAW = WORKFLOW_PATH.read_text()
WORKFLOW = yaml.safe_load(RAW)
JOBS = WORKFLOW["jobs"]


def _steps(job: str) -> str:
    """The job re-serialised as one searchable blob.

    `width` is set high so PyYAML does not line-wrap a phrase mid-assertion.
    """
    return yaml.safe_dump(JOBS[job], width=10**6)


class TestTriggers:
    def test_ci_runs_on_pull_requests(self):
        # PyYAML parses a bare `on:` key as the boolean True.
        triggers = WORKFLOW.get("on") or WORKFLOW.get(True)
        assert "pull_request" in triggers

    def test_ci_runs_on_the_main_branch(self):
        triggers = WORKFLOW.get("on") or WORKFLOW.get(True)
        assert "main" in triggers["push"]["branches"]

    def test_stale_runs_are_cancelled(self):
        assert WORKFLOW["concurrency"]["cancel-in-progress"] is True


class TestLeastPrivilege:
    def test_the_workflow_cannot_write_to_the_repository(self):
        """A workflow with write access is a supply-chain surface."""
        assert WORKFLOW["permissions"] == {"contents": "read"}

    def test_every_action_is_pinned_to_a_major_version_at_least(self):
        import re

        uses = re.findall(r"uses:\s*(\S+)", RAW)
        assert uses
        for action in uses:
            assert "@" in action, f"{action} is unpinned"
            assert not action.endswith("@main"), f"{action} tracks a moving branch"
            assert not action.endswith("@master"), f"{action} tracks a moving branch"


class TestQualityGates:
    @pytest.mark.parametrize(
        "job",
        ["lint", "types", "test", "constitution", "design", "filmkit", "security", "container"],
    )
    def test_the_job_exists(self, job: str):
        assert job in JOBS

    def test_linting_is_blocking(self):
        assert "ruff check" in _steps("lint")

    def test_formatting_is_checked_not_just_available(self):
        assert "ruff format --check" in _steps("lint")

    def test_type_checking_runs(self):
        assert "mypy" in _steps("types")

    def test_the_core_coverage_gate_is_ninety_percent(self):
        steps = _steps("test")
        assert "--cov=anuvritti.domain" in steps
        assert "--cov-fail-under=90" in steps

    def test_coverage_builds_the_ignored_world_before_pytest_collects_design_tests(self):
        steps = _steps("test")
        assert steps.index("packages/world run build") < steps.index("pytest --cov")

    def test_the_overall_coverage_gate_matches_the_local_ninety_percent_gate(self):
        assert "--cov-fail-under=90" in _steps("test")

    @pytest.mark.parametrize("package", ["packages/world", "packages/client", "apps/anuvritti"])
    def test_every_npm_suite_runs(self, package: str):
        assert f"npm --prefix {package} test" in _steps("design")

    def test_filmkit_runs_its_own_quality_gate(self):
        steps = _steps("filmkit")
        assert "make -C packages/filmkit check" in steps

    def test_no_step_disables_a_failure(self):
        """`continue-on-error` turns a gate into a suggestion."""
        assert "continue-on-error: true" not in RAW


class TestTheConstitutionIsEnforcedByCi:
    def test_the_constitution_suite_runs_as_its_own_job(self):
        """PRD 47 boundaries fail the build, not a code review."""
        assert "tests/constitution" in _steps("constitution")

    def test_the_architecture_fitness_functions_run(self):
        assert "tests/architecture" in _steps("constitution")


class TestSecurity:
    def test_dependencies_are_audited(self):
        assert "pip-audit" in _steps("security")

    def test_static_analysis_runs(self):
        assert "bandit" in _steps("security")

    def test_secrets_are_scanned_for(self):
        assert "gitleaks" in _steps("security")

    def test_a_committed_env_file_fails_the_build(self):
        """PRD 44 - zero secrets in the repository."""
        assert ".env" in _steps("security")


class TestContainer:
    def test_the_image_is_built_in_ci(self):
        assert "docker/build-push-action" in _steps("container")

    def test_the_image_is_never_pushed_from_ci(self):
        assert "push: false" in _steps("container")

    def test_ci_verifies_the_image_does_not_run_as_root(self):
        assert "would run as root" in _steps("container")

    def test_ci_verifies_production_refuses_to_start_without_a_key(self):
        """PRD 44 - the promise is only real if something checks it."""
        assert "ANUVRITTI_MEDIA_KEY" in _steps("container")

    def test_the_image_is_scanned_for_vulnerabilities(self):
        steps = _steps("container")
        assert "trivy" in steps
        assert "CRITICAL" in steps

    def test_the_container_job_waits_for_the_quality_jobs(self):
        assert set(JOBS["container"]["needs"]) >= {"lint", "types", "test"}


class TestTheFinalGate:
    def test_there_is_a_single_required_check(self):
        assert "ci" in JOBS

    def test_it_depends_on_every_other_job(self):
        others = {name for name in JOBS if name != "ci"}
        assert set(JOBS["ci"]["needs"]) == others

    def test_it_fails_when_any_dependency_fails(self):
        assert "failure" in _steps("ci")
