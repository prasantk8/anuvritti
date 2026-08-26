"""The caches stay bounded, and pruning never costs truth."""

from __future__ import annotations

import os
import time

from filmkit import cachestore


def _entry(root, store, filename, size=1024):
    directory = root / store
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(b"x" * size)
    return path


def test_survey_reports_every_store_including_the_empty_ones(tmp_path):
    _entry(tmp_path, "frames", "a.png")
    _entry(tmp_path, "tts", "a.mp3")
    reports = {r.name: r for r in cachestore.survey(tmp_path)}
    assert reports["frames"].entries == 1
    assert reports["frames"].bytes == 1024
    assert reports["scenes"].entries == 0


def test_a_file_the_store_does_not_claim_is_not_counted(tmp_path):
    """Each store lists its own extensions; a stray file is not cache."""
    _entry(tmp_path, "frames", "notes.txt")
    assert cachestore.survey(tmp_path)[1].entries == 0


def test_a_hit_records_that_the_entry_is_still_wanted(tmp_path):
    path = _entry(tmp_path, "frames", "a.png")
    os.utime(path, (time.time() - 90 * 86400,) * 2)
    assert cachestore.survey(tmp_path)[1].oldest_use_days > 80

    cachestore.touch(path)
    assert cachestore.survey(tmp_path)[1].oldest_use_days < 1


def test_recording_a_hit_never_fails_a_build(tmp_path):
    """The worst case of a failed touch is wasted time, so it is swallowed."""
    cachestore.touch(tmp_path / "does" / "not" / "exist.png")


def test_prune_removes_only_what_nothing_has_asked_for(tmp_path):
    stale = _entry(tmp_path, "frames", "stale.png")
    fresh = _entry(tmp_path, "frames", "fresh.png")
    os.utime(stale, (time.time() - 40 * 86400,) * 2)

    removed, freed = cachestore.prune(30, tmp_path)
    assert (removed, freed) == (1, 1024)
    assert fresh.is_file() and not stale.is_file()


def test_pruning_a_store_that_was_never_created_is_not_an_error(tmp_path):
    assert cachestore.prune(30, tmp_path) == (0, 0)


def test_clear_empties_every_store(tmp_path):
    _entry(tmp_path, "frames", "a.png")
    _entry(tmp_path, "scenes", "a.mp4")
    removed, _ = cachestore.clear(tmp_path)
    assert removed == 2
    assert all(report.entries == 0 for report in cachestore.survey(tmp_path))


def test_a_report_serialises_without_its_absolute_path(tmp_path):
    """A manifest should say how much, not where somebody's home directory is."""
    _entry(tmp_path, "tts", "a.mp3")
    payload = cachestore.survey(tmp_path)[0].to_json()
    assert payload == {"store": "tts", "entries": 1, "bytes": 1024, "oldest_use_days": 0.0}
    assert "path" not in payload


def test_sizes_read_as_sizes():
    assert cachestore.human(512) == "512.0 B"
    assert cachestore.human(2048) == "2.0 KB"
    assert cachestore.human(5 * 1024**4) == "5.0 TB"
