"""Timing arithmetic, and the refusal to hide a conflict."""

from __future__ import annotations

import inspect

import pytest

from filmkit import timing
from filmkit.narration import Narration
from filmkit.timing import Beat


def _track(scene_id, duration, words) -> Narration:
    return Narration(
        scene_id=scene_id,
        voice="v",
        rate="+0%",
        pitch="+0Hz",
        text="",
        word_count=words,
        duration_sec=duration,
        sha256="",
        path="",
        cache_key="",
    )


def _plan(beats, tracks, **kwargs):
    return timing.plan(
        beats,
        tracks,
        target_wpm=kwargs.get("target_wpm", 150.0),
        target_sec=kwargs.get("target_sec", 120.0),
        tolerance_sec=kwargs.get("tolerance_sec", 5.0),
    )


class TestTheEstimateCanNeverDecideHowLongSomethingIsOnScreen:
    def test_the_function_that_sets_the_length_cannot_see_a_word_rate(self):
        """Structural, not stated: there is no WPM in scope to reach for."""
        parameters = set(inspect.signature(timing.visual_seconds).parameters)
        assert parameters == {"beat", "audio_sec"}
        assert not any("wpm" in field for field in Beat.__dataclass_fields__)

    def test_a_scene_holds_for_its_voice_plus_the_padding_that_was_asked_for(self):
        beat = Beat(id="01_a", type="card", lead_in_sec=0.5, tail_sec=1.0)
        assert timing.visual_seconds(beat, 10.0) == 11.5

    def test_a_declared_duration_is_a_floor_not_a_ceiling(self):
        beat = Beat(
            id="01_a", type="card", mode="duration", seconds=3.0, lead_in_sec=0.0, tail_sec=0.0
        )
        assert timing.visual_seconds(beat, 9.0) == 9.0, "cutting the voice off is not an option"

    def test_a_declared_duration_longer_than_the_voice_is_honoured(self):
        beat = Beat(
            id="01_a", type="card", mode="duration", seconds=12.0, lead_in_sec=0.0, tail_sec=0.0
        )
        assert timing.visual_seconds(beat, 9.0) == 12.0

    def test_a_minimum_lifts_a_scene_that_would_otherwise_flash_past(self):
        beat = Beat(id="01_a", type="card", min_sec=4.0, lead_in_sec=0.0, tail_sec=0.0)
        assert timing.visual_seconds(beat, 1.0) == 4.0


class TestAConflictIsReportedNotAbsorbed:
    def test_a_script_that_runs_long_says_so_and_renders_the_honest_length(self):
        report = _plan(
            [Beat(id="01_a", type="card", lead_in_sec=0, tail_sec=0)],
            [_track("01_a", 131.0, 324)],
            target_sec=120.0,
            tolerance_sec=10.0,
        )
        assert report.conflict
        assert report.status == timing.CONFLICT
        assert report.delta_vs_target > 10
        assert report.actual_sec == 131.0, "the rendered length is the real one, not the target"

    def test_within_tolerance_is_not_a_conflict(self):
        report = _plan(
            [Beat(id="01_a", type="card", lead_in_sec=0, tail_sec=0)],
            [_track("01_a", 122.0, 300)],
            target_sec=120.0,
            tolerance_sec=5.0,
        )
        assert not report.conflict and report.status == timing.WITHIN

    def test_a_script_that_runs_short_is_a_conflict_too(self):
        """Tolerance is a distance, not a maximum - fifty seconds under is news."""
        report = _plan(
            [Beat(id="01_a", type="card", lead_in_sec=0, tail_sec=0)],
            [_track("01_a", 70.0, 150)],
            target_sec=120.0,
            tolerance_sec=10.0,
        )
        assert report.conflict


class TestScenesLieEndToEnd:
    def test_starts_accumulate_and_drift_against_the_script_is_measured(self):
        report = _plan(
            [
                Beat(id="01_a", type="card", lead_in_sec=0, tail_sec=0, nominal_start_sec=0),
                Beat(id="02_b", type="card", lead_in_sec=0, tail_sec=0, nominal_start_sec=15),
            ],
            [_track("01_a", 20.0, 50), _track("02_b", 10.0, 25)],
        )
        assert report.scenes[1].start_sec == 20.0
        assert report.scenes[1].nominal_drift_sec == 5.0
        assert report.scenes[1].end_sec == 30.0
        assert report.actual_sec == 30.0

    def test_a_beat_with_no_timecode_has_no_drift_to_report(self):
        report = _plan([Beat(id="01_a", type="card")], [_track("01_a", 5.0, 10)])
        assert report.scenes[0].nominal_start_sec is None
        assert report.scenes[0].nominal_drift_sec is None

    def test_a_beat_carries_its_reason_and_its_anchors_into_the_report(self):
        report = _plan(
            [
                Beat(
                    id="01_a",
                    type="card",
                    mode="duration",
                    seconds=2.0,
                    wait_for=("done",),
                    reason="held card",
                )
            ],
            [_track("01_a", 1.0, 3)],
        )
        assert report.scenes[0].reason == "held card"
        assert report.scenes[0].wait_for == ["done"]
        assert report.scenes[0].mode == "duration"


class TestThePaceAViewerActuallyExperiences:
    def test_effective_wpm_counts_the_silence_too(self):
        report = _plan(
            [Beat(id="01_a", type="card", lead_in_sec=1.0, tail_sec=1.0)],
            [_track("01_a", 58.0, 150)],
        )
        assert report.actual_sec == 60.0
        assert report.effective_wpm == pytest.approx(150.0)
        assert report.actual_sec > sum(s.audio_sec for s in report.scenes)

    def test_an_empty_film_has_no_pace_rather_than_a_division_by_zero(self):
        report = _plan([], [])
        assert report.effective_wpm == 0.0
        assert report.to_json()["effective_wpm"] == 0.0

    def test_the_estimate_is_kept_beside_the_measurement_never_instead_of_it(self):
        report = _plan(
            [Beat(id="01_a", type="card", lead_in_sec=0, tail_sec=0)],
            [_track("01_a", 40.0, 150)],
            target_wpm=150.0,
        )
        assert report.estimated_sec == pytest.approx(60.0)
        assert report.actual_sec == 40.0
        assert report.delta_estimate_vs_actual == pytest.approx(-20.0)


class TestTheReportReads:
    def test_json_carries_every_number_the_text_shows(self):
        report = _plan(
            [Beat(id="01_a", type="card", nominal_start_sec=0)],
            [_track("01_a", 5.0, 12)],
            target_sec=5.9,
        )
        payload = report.to_json()
        assert payload["status"] == timing.WITHIN
        assert payload["scenes"][0]["scene_id"] == "01_a"
        assert payload["scenes"][0]["type"] == "card"

    def test_text_names_the_status_and_every_scene(self):
        report = _plan(
            [
                Beat(id="01_a", type="card", nominal_start_sec=0),
                Beat(id="02_b", type="card"),
            ],
            [_track("01_a", 5.0, 12), _track("02_b", 4.0, 9)],
        )
        text = report.render_text()
        assert timing.CONFLICT in text
        assert "01_a" in text and "02_b" in text

    def test_a_film_with_no_length_reports_no_pace_in_words(self):
        assert "n/a" in _plan([], []).render_text()


class TestABeatCannotBeMalformed:
    def test_a_duration_mode_with_no_duration_is_refused_at_construction(self):
        """The alternative is a scene that silently falls back to its audio length."""
        with pytest.raises(ValueError, match="not a duration"):
            Beat(id="01_a", type="card", mode="duration")

    def test_a_duration_of_zero_is_a_duration(self):
        assert (
            timing.visual_seconds(
                Beat(
                    id="01_a",
                    type="card",
                    mode="duration",
                    seconds=0.0,
                    lead_in_sec=0.0,
                    tail_sec=0.0,
                ),
                4.0,
            )
            == 4.0
        )
