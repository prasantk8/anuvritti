"""An account of a compile is only worth what it can be checked against."""

from __future__ import annotations

import json

from filmkit import manifest


def test_a_missing_tool_is_recorded_as_unknown_not_as_an_error():
    found = manifest.tool_versions([("nope", ("a-binary-that-is-not-installed", "--version"))])
    assert found == {"nope": None}


def test_a_present_tool_reports_its_version(runner):
    runner.stdout = "ffmpeg version 7.1\nbuilt with..."
    import sys

    found = manifest.tool_versions([("python", (sys.executable, "--version"))], runner=runner)
    assert found["python"] == "ffmpeg version 7.1"


def test_a_package_that_is_installed_reports_its_distribution_version():
    found = manifest.distribution_versions(["pytest", "not-a-real-distribution"])
    assert found["pytest"] is not None
    assert found["not-a-real-distribution"] is None


def test_a_directory_that_is_not_a_repository_has_no_commit(tmp_path):
    assert manifest.git_commit(tmp_path) is None


def test_a_repository_reports_the_commit_its_inputs_were_at(tmp_path, runner):
    (tmp_path / ".git").mkdir()
    runner.stdout = "abc123\n"
    assert manifest.git_commit(tmp_path, runner=runner) == "abc123"


def test_a_repository_that_has_no_commits_yet_reports_none(tmp_path, runner):
    (tmp_path / ".git").mkdir()
    runner.stdout = "  \n"
    assert manifest.git_commit(tmp_path, runner=runner) is None


def test_every_output_that_exists_is_hashed(tmp_path):
    real = tmp_path / "film.mp4"
    real.write_bytes(b"video")
    digests = manifest.output_digests({"mp4": real, "webm": tmp_path / "gone.webm"})
    assert set(digests) == {"mp4"}
    assert digests["mp4"]["bytes"] == 5
    assert len(digests["mp4"]["sha256"]) == 64


def test_a_file_that_is_not_there_is_not_claimed(tmp_path):
    assert manifest.output_digests({"mp4": tmp_path / "gone.mp4"}) == {}


def test_disk_is_reported_per_named_path(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "a").write_bytes(b"x" * 7)
    assert manifest.disk(tmp_path / "artifacts", tmp_path / "cache") == {"artifacts": 7, "cache": 0}


def test_the_only_timestamp_is_when_it_was_written():
    written = manifest.stamp()
    assert written.endswith("Z") and len(written) == 20


def test_a_manifest_round_trips_through_a_directory_that_did_not_exist(tmp_path):
    path = manifest.write({"schema": "x", "result": "PASS"}, tmp_path / "deep" / "m.json")
    assert json.loads(path.read_text())["result"] == "PASS"


def test_the_browser_version_is_absent_rather_than_fatal_without_a_browser():
    """An inventory entry must never be the reason a finished film is thrown away."""
    assert manifest.browser_version() is None or isinstance(manifest.browser_version(), str)
