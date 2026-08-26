"""Measured never estimated, and honest about whose voice it is."""

from __future__ import annotations

import pytest

from filmkit import narration
from filmkit.narration import Line, NarrationError, Studio, Voice

VOICE = Voice(name="a-voice", rate="+0%", pitch="+0Hz")


def _studio(workspace, synthesiser, runner, **kwargs):
    runner.stdout = "3.5\n"
    return Studio(workspace=workspace, synthesiser=synthesiser, runner=runner, **kwargs)


class TestWordsAreCountedAsAListenerWouldHearThem:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("one two three", 3),
            ("don't stop", 2),
            ("state-of-the-art", 1),
            ("", 0),
            ("-- ... --", 0),
            ("2026 was the year", 4),
        ],
    )
    def test_count(self, text, expected):
        assert narration.count_words(text) == expected


class TestTheCacheKeyCoversEverythingThatChangesTheSound:
    def test_the_same_words_in_the_same_voice_is_the_same_key(self):
        a = narration.cache_key("hello there", VOICE, synth_version="v1")
        b = narration.cache_key("hello there", VOICE, synth_version="v1")
        assert a == b

    @pytest.mark.parametrize(
        "text,voice,version",
        [
            ("hello world", VOICE, "v1"),
            ("hello there", Voice(name="other"), "v1"),
            ("hello there", Voice(name="a-voice", rate="-10%"), "v1"),
            ("hello there", Voice(name="a-voice", pitch="+5Hz"), "v1"),
            ("hello there", VOICE, "v2"),
        ],
    )
    def test_any_change_is_a_different_key(self, text, voice, version):
        base = narration.cache_key("hello there", VOICE, synth_version="v1")
        assert narration.cache_key(text, voice, synth_version=version) != base

    def test_a_voice_can_be_read_from_the_shape_a_config_file_has(self):
        assert Voice.from_dict({"name": "x"}) == Voice(name="x", rate="+0%", pitch="+0Hz")
        assert Voice.from_dict({"name": "x", "rate": "-5%"}).rate == "-5%"


class TestDurationIsMeasured:
    def test_it_comes_from_the_probe_not_the_text(self, tmp_path, runner):
        runner.stdout = "12.25\n"
        assert narration.measure(tmp_path / "a.mp3", runner=runner) == 12.25
        assert runner.last[0] == "ffprobe"

    def test_a_probe_that_says_nothing_useful_is_a_failure_not_a_guess(self, tmp_path, runner):
        runner.stdout = "N/A"
        with pytest.raises(NarrationError, match="no duration"):
            narration.measure(tmp_path / "a.mp3", runner=runner)

    def test_zero_length_audio_is_refused(self, tmp_path, runner):
        runner.stdout = "0.0"
        with pytest.raises(NarrationError, match="zero-duration"):
            narration.measure(tmp_path / "a.mp3", runner=runner)


class TestARealVoiceIsTakenAsItIs:
    def test_it_is_copied_measured_and_marked_recorded(self, tmp_path, workspace, runner):
        runner.stdout = "4.2\n"
        source = tmp_path / "papa.m4a"
        source.write_bytes(b"his own voice")

        track = narration.adopt(
            Line("01_why", "I want to see his face."),
            source,
            workspace=workspace,
            project="p",
            runner=runner,
        )
        assert track.origin == narration.RECORDED
        assert track.is_real_voice
        assert track.duration_sec == 4.2
        assert track.word_count == 6

    def test_the_bytes_are_unchanged(self, tmp_path, workspace, runner):
        runner.stdout = "4.2\n"
        source = tmp_path / "papa.m4a"
        source.write_bytes(b"his own voice")
        track = narration.adopt(
            Line("01_why", "x"), source, workspace=workspace, project="p", runner=runner
        )
        from pathlib import Path

        assert Path(track.path).read_bytes() == b"his own voice"
        assert Path(track.path).suffix == ".m4a"

    def test_its_content_address_is_its_own_hash(self, tmp_path, workspace, runner):
        """There is no request that would produce it again. A person said it once."""
        runner.stdout = "4.2\n"
        source = tmp_path / "papa.m4a"
        source.write_bytes(b"his own voice")
        track = narration.adopt(
            Line("01_why", "x"), source, workspace=workspace, project="p", runner=runner
        )
        assert track.cache_key == track.sha256

    def test_a_synthesised_track_never_claims_to_be_recorded(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        tracks, _ = studio.build([Line("01_a", "hello")], VOICE, project="p")
        assert tracks[0].origin == narration.SYNTHETIC
        assert not tracks[0].is_real_voice


class TestSynthesisIsCachedByContent:
    def test_a_cold_build_synthesises_and_measures(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        tracks, stats = studio.build([Line("01_a", "hello")], VOICE, project="p")
        assert stats == {"hits": 0, "misses": 1}
        assert synthesiser.said == ["hello"]
        assert tracks[0].duration_sec == 3.5
        assert tracks[0].cached is False

    def test_the_second_build_never_calls_out_again(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        studio.build([Line("01_a", "hello")], VOICE, project="p")
        tracks, stats = studio.build([Line("01_a", "hello")], VOICE, project="p")
        assert stats == {"hits": 1, "misses": 0}
        assert synthesiser.said == ["hello"], "a warm build must not synthesise"
        assert tracks[0].cached is True

    def test_a_one_word_edit_regenerates_only_that_line(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        lines = [Line("01_a", "hello"), Line("02_b", "there")]
        studio.build(lines, VOICE, project="p")
        studio.build([Line("01_a", "hello"), Line("02_b", "there now")], VOICE, project="p")
        assert synthesiser.said == ["hello", "there", "there now"]

    def test_several_lines_may_be_synthesised_at_once(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        lines = [Line(f"{i:02d}_x", f"line {i}") for i in range(6)]
        tracks, stats = studio.build(lines, VOICE, project="p", workers=4)
        assert stats["misses"] == 6
        assert [t.scene_id for t in tracks] == [line.id for line in lines]

    def test_offline_refuses_rather_than_reaching_out(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        with pytest.raises(NarrationError, match="offline"):
            studio.build([Line("01_a", "hello")], VOICE, project="p", offline=True)
        assert synthesiser.said == []

    def test_offline_is_fine_once_the_store_is_warm(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        studio.build([Line("01_a", "hello")], VOICE, project="p")
        tracks, stats = studio.build([Line("01_a", "hello")], VOICE, project="p", offline=True)
        assert stats["hits"] == 1 and tracks[0].duration_sec == 3.5

    def test_the_plan_is_reported_in_line_order_before_any_work_starts(
        self, workspace, synthesiser, runner
    ):
        from filmkit.reporting import MISS, Recorder

        recorder = Recorder()
        studio = _studio(workspace, synthesiser, runner, reporter=recorder)
        studio.build([Line("01_a", "one two"), Line("02_b", "three")], VOICE, project="p")
        said = [what for _, what in recorder.lines]
        assert said == ["audio 01_a (2 words)", "audio 02_b (1 words)"]
        assert {verb for verb, _ in recorder.lines} == {MISS}

    def test_a_warm_line_is_reported_as_a_hit_without_its_word_count(
        self, workspace, synthesiser, runner
    ):
        from filmkit.reporting import HIT, Recorder

        studio = _studio(workspace, synthesiser, runner)
        studio.build([Line("01_a", "one two")], VOICE, project="p")
        recorder = Recorder()
        _studio(workspace, synthesiser, runner, reporter=recorder).build(
            [Line("01_a", "one two")], VOICE, project="p"
        )
        assert recorder.lines == [(HIT, "audio 01_a")]

    def test_a_track_serialises_everything_a_manifest_needs(self, workspace, synthesiser, runner):
        studio = _studio(workspace, synthesiser, runner)
        tracks, _ = studio.build([Line("01_a", "hello")], VOICE, project="p")
        payload = tracks[0].to_json()
        assert payload["origin"] == "synthetic"
        assert payload["voice"] == "a-voice"
        assert payload["sha256"] and payload["cache_key"]
