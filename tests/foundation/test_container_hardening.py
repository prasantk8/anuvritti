"""TASK-402 - the container is part of the security boundary.

A Dockerfile is production code. These assertions are the ones a reviewer would make by
hand every time and eventually stop making.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
DOCKERIGNORE = (ROOT / ".dockerignore").read_text()
STAGES = re.findall(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", DOCKERFILE, re.MULTILINE | re.IGNORECASE)
EXTERNAL_BASES = [(base, stage) for base, stage in STAGES if ":" in base]


class TestMultiStage:
    def test_the_build_is_multi_stage(self):
        assert len(STAGES) >= 2, "a single-stage image ships the build toolchain"

    def test_the_final_stage_is_named_runtime(self):
        assert STAGES[-1][1] == "runtime"

    def test_only_the_virtualenv_crosses_the_stage_boundary(self):
        copies = re.findall(r"COPY --from=build[^\n]*", DOCKERFILE)
        assert copies, "the runtime stage must take its artefact from the build stage"
        assert all("/opt/venv" in line for line in copies)

    def test_no_compiler_or_build_tooling_is_installed_in_the_runtime_stage(self):
        """Checked against what the stage *installs*, not against prose in a LABEL."""
        runtime = DOCKERFILE[DOCKERFILE.index("AS runtime-base") :]
        installs = " ".join(re.findall(r"^RUN [^\n]*(?:\\\n[^\n]*)*", runtime, re.MULTILINE))
        for tool in ("build-essential", "gcc", "g++", "make", "git", "curl", "wget"):
            assert not re.search(rf"install[^\n]*\b{re.escape(tool)}\b", installs), tool


class TestBaseImage:
    def test_the_base_is_a_slim_pinned_image(self):
        for base, _stage in EXTERNAL_BASES:
            assert "slim" in base, f"{base} is larger than it needs to be"

    def test_the_base_tag_is_specific_not_latest(self):
        for base, _ in EXTERNAL_BASES:
            assert not base.endswith(":latest")
            assert ":" in base, f"{base} has no tag at all"

    def test_the_python_version_matches_the_project_floor(self):
        import tomllib

        requires = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
            "requires-python"
        ]
        assert all(requires.replace(">=", "") in base for base, _ in EXTERNAL_BASES)

    def test_security_updates_are_applied(self):
        assert "apt-get upgrade" in DOCKERFILE

    def test_runtime_can_probe_voice_without_shipping_a_browser(self):
        assert "apt-get install -y --no-install-recommends ffmpeg" in DOCKERFILE
        assert "playwright" not in DOCKERFILE.lower()
        assert "chromium" not in DOCKERFILE.lower()

    def test_the_apt_cache_is_not_left_in_a_layer(self):
        assert "rm -rf /var/lib/apt/lists/*" in DOCKERFILE


class TestNonRoot:
    def test_a_dedicated_user_is_created(self):
        assert "useradd" in DOCKERFILE
        assert "groupadd" in DOCKERFILE

    def test_the_container_does_not_run_as_root(self):
        users = re.findall(r"^USER\s+(\S+)", DOCKERFILE, re.MULTILINE)
        assert users, "no USER directive: the container would run as root"
        assert not users[-1].startswith("root")
        assert not users[-1].startswith("0")

    def test_the_user_is_a_system_account_with_no_login_shell(self):
        assert "--system" in DOCKERFILE
        assert "nologin" in DOCKERFILE

    def test_the_user_directive_comes_after_the_last_install(self):
        """Otherwise the build silently needs root anyway."""
        last_user = DOCKERFILE.rindex("USER ")
        last_run = DOCKERFILE.rindex("RUN ")
        assert last_user > last_run

    def test_the_data_directory_is_owned_by_the_runtime_user(self):
        assert "chown -R anuvritti:anuvritti /var/lib/anuvritti" in DOCKERFILE


class TestRuntimeConfiguration:
    def test_no_secret_is_baked_into_the_image(self):
        """PRD 44 - zero secrets. The key is supplied at run time or the app refuses."""
        assert "ANUVRITTI_MEDIA_KEY=" not in DOCKERFILE
        for word in ("password", "secret", "token", "api_key"):
            assert not re.search(rf"ENV\s+\w*{word}", DOCKERFILE, re.IGNORECASE)

    def test_the_family_archive_lives_on_a_volume_not_in_the_image(self):
        assert 'VOLUME ["/var/lib/anuvritti"]' in DOCKERFILE

    def test_the_image_defaults_to_the_production_environment(self):
        assert "ANUVRITTI_ENV=production" in DOCKERFILE

    def test_there_is_a_healthcheck(self):
        assert "HEALTHCHECK" in DOCKERFILE
        assert "/health" in DOCKERFILE

    def test_the_server_does_not_advertise_itself(self):
        assert "--no-server-header" in DOCKERFILE

    def test_output_is_unbuffered_so_logs_are_a_live_stream(self):
        """12-factor: logs are an event stream, not a file flushed on exit."""
        assert "PYTHONUNBUFFERED=1" in DOCKERFILE


class TestBuildContext:
    @pytest.mark.parametrize(
        "path", [".git", ".venv", "tests", ".env", "*.db", "__pycache__", "var"]
    )
    def test_the_build_context_excludes_it(self, path: str):
        assert path in DOCKERIGNORE

    def test_a_real_env_file_can_never_be_copied_in(self):
        assert ".env" in DOCKERIGNORE
        assert ".env.*" in DOCKERIGNORE

    def test_the_example_env_is_still_allowed_through(self):
        assert "!.env.example" in DOCKERIGNORE

    def test_the_tracker_is_not_shipped_to_production(self):
        assert "tracker.json" in DOCKERIGNORE
