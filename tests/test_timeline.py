"""The timeline is the last place a sync error can be caught cheaply."""

from __future__ import annotations

import json

from filmkit.timeline import FrameEntry, SceneEntry, Timeline


def _scene(scene_id="01_a", audio=10.0, visual=11.0, frames=(5.5, 5.5), **kwargs):
    return SceneEntry(
        id=scene_id,
        type="terminal",
        start_sec=0.0,
        audio_path="a.mp3",
        audio_duration_sec=audio,
        visual_duration_sec=visual,
        frames=[FrameEntry(f"{i}.png", d, f"s{i}") for i, d in enumerate(frames)],
        narration="x",
        **kwargs,
    )


class TestFramesMustAddUpToTheSceneTheyBelongTo:
    def test_frames_summing_to_the_scene_is_clean(self):
        timeline = Timeline("p", 60, 1920, 1080, [_scene(visual=11.0, frames=(5.5, 5.5))])
        assert timeline.check_sync(0.25) == []

    def test_drift_beyond_tolerance_is_reported(self):
        timeline = Timeline("p", 60, 1920, 1080, [_scene(visual=11.0, frames=(5.5, 4.0))])
        problems = timeline.check_sync(0.25)
        assert len(problems) == 1 and "drift" in problems[0]

    def test_drift_inside_tolerance_is_not(self):
        timeline = Timeline("p", 60, 1920, 1080, [_scene(visual=11.0, frames=(5.5, 5.4))])
        assert timeline.check_sync(0.25) == []

    def test_audio_longer_than_its_scene_is_named_as_truncation(self):
        """This is the failure `-shortest` would have silently absorbed."""
        timeline = Timeline("p", 60, 1920, 1080, [_scene(audio=12.0, visual=11.0)])
        assert any("cut off" in problem for problem in timeline.check_sync(0.25))

    def test_a_scene_can_fail_both_checks_at_once(self):
        timeline = Timeline("p", 60, 1920, 1080, [_scene(audio=20.0, visual=11.0, frames=(1.0,))])
        assert len(timeline.check_sync(0.25)) == 2


class TestArithmetic:
    def test_duration_is_the_sum_of_scenes(self):
        timeline = Timeline(
            "p",
            60,
            1920,
            1080,
            [
                _scene("01_a", visual=11.0, frames=(5.5, 5.5)),
                _scene("02_b", visual=9.0, frames=(4.5, 4.5)),
            ],
        )
        assert timeline.duration_sec == 20.0

    def test_delta_is_padding_never_a_cut_in_a_healthy_film(self):
        assert abs(_scene(audio=10.0, visual=11.0).delta - 1.0) < 1e-9

    def test_an_empty_film_is_zero_long(self):
        assert Timeline("p", 60, 1920, 1080, []).duration_sec == 0


class TestProvenanceSurvivesSerialisation:
    def test_what_a_scene_showed_and_what_it_cites_are_both_kept(self):
        scene = _scene(shows=["a-label"], cites=[{"kind": "spark", "id": "s-1"}])
        payload = scene.to_json()
        assert payload["shows"] == ["a-label"]
        assert payload["cites"] == [{"kind": "spark", "id": "s-1"}]

    def test_a_scene_with_nothing_to_cite_says_so_rather_than_omitting_the_field(self):
        assert _scene().to_json()["cites"] == []

    def test_the_timeline_round_trips_to_disk(self, tmp_path):
        timeline = Timeline("p", 60, 1920, 1080, [_scene(cites=[{"id": "s-1"}])])
        path = timeline.write(tmp_path / "nested" / "t.json")
        data = json.loads(path.read_text())
        assert data["scene_count"] == 1
        assert data["resolution"] == "1920x1080"
        assert data["scenes"][0]["cites"] == [{"id": "s-1"}]

    def test_two_scenes_do_not_share_a_provenance_list(self):
        """A mutable default here would make every scene cite the first one's sources."""
        one, two = _scene("01_a"), _scene("02_b")
        one.cites.append({"id": "s-1"})
        assert two.cites == []
