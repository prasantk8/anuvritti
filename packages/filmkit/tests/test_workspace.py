"""A workspace is given, never found."""

from __future__ import annotations

from pathlib import Path

from filmkit.workspace import Workspace


def test_under_lays_out_the_two_directories(tmp_path):
    space = Workspace.under(tmp_path)
    assert space.artifacts == tmp_path / "artifacts"
    assert space.cache == tmp_path / "cache"


def test_artifact_and_store_create_what_they_name(tmp_path):
    space = Workspace.under(tmp_path)
    assert space.artifact("audio", "p").is_dir()
    assert space.store("tts").is_dir()


def test_two_films_on_one_machine_do_not_share_an_artifact_directory(tmp_path):
    one = Workspace.under(tmp_path / "one")
    two = Workspace.under(tmp_path / "two")
    assert one.artifact("audio", "p") != two.artifact("audio", "p")


def test_a_workspace_can_split_output_from_cache_across_filesystems(tmp_path):
    """The two directories are independent on purpose: cache is disposable."""
    space = Workspace(artifacts=tmp_path / "out", cache=Path(tmp_path) / "elsewhere" / "cache")
    assert space.store("frames").is_dir()
    assert not (space.artifacts / "frames").exists()
