"""A cache entry exists whole or not at all."""

from __future__ import annotations

from filmkit import files


def test_ensure_dir_is_idempotent(tmp_path):
    target = tmp_path / "a" / "b"
    assert files.ensure_dir(target) == target
    assert files.ensure_dir(target).is_dir()


def test_atomic_copy_leaves_no_temporary_behind(tmp_path):
    source = tmp_path / "in"
    source.write_bytes(b"data")
    destination = tmp_path / "store" / "out"
    files.atomic_copy(source, destination)
    assert destination.read_bytes() == b"data"
    assert [p.name for p in destination.parent.iterdir()] == ["out"]


def test_atomic_copy_replaces_an_existing_entry(tmp_path):
    source = tmp_path / "in"
    destination = tmp_path / "out"
    destination.write_bytes(b"old")
    source.write_bytes(b"new")
    files.atomic_copy(source, destination)
    assert destination.read_bytes() == b"new"


def test_disk_usage_counts_files_not_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a").write_bytes(b"x" * 10)
    (tmp_path / "b").write_bytes(b"y" * 5)
    assert files.disk_usage(tmp_path) == 15


def test_a_missing_directory_uses_no_disk(tmp_path):
    assert files.disk_usage(tmp_path / "nope") == 0
