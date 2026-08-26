"""Nothing is re-encoded that has not changed, and nothing is trimmed to fit."""

from __future__ import annotations

import pytest

from filmkit import compositor
from filmkit.reporting import HIT, MISS, Recorder
from filmkit.timeline import FrameEntry, SceneEntry, Timeline


def _scene(index=1, audio_path=None, frames=((1.0, "a"),), visual=1.0):
    return SceneEntry(
        id=f"{index:02d}_scene",
        type="card",
        start_sec=float(index),
        audio_path=str(audio_path or "/nowhere/a.mp3"),
        audio_duration_sec=1.0,
        visual_duration_sec=visual,
        frames=[FrameEntry(f"/frames/{i}.png", d, label) for i, (d, label) in enumerate(frames)],
        narration="x",
    )


def _timeline(scenes):
    return Timeline("p", 60, 1920, 1080, scenes)


def _writes(path, payload):
    """What a real encoder leaves behind, so the copy-into-store path is exercised."""

    def on_call(argv, kwargs):
        path.write_bytes(payload)

    return on_call


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"audio")
    return path


class TestTheVoiceIsNeverCutToFitThePicture:
    def test_shortest_is_never_passed_to_the_encoder(self, tmp_path, workspace, runner, audio):
        compositor.render_scene(
            _scene(audio_path=audio),
            _timeline([]),
            tmp_path,
            workspace=workspace,
            runner=runner,
        )
        assert "-shortest" not in runner.last

    def test_the_audio_is_padded_with_real_silence_instead(
        self, tmp_path, workspace, runner, audio
    ):
        compositor.render_scene(
            _scene(audio_path=audio),
            _timeline([]),
            tmp_path,
            workspace=workspace,
            runner=runner,
        )
        assert "apad" in runner.flat()

    def test_the_scene_is_cut_to_its_own_declared_length(self, tmp_path, workspace, runner, audio):
        compositor.render_scene(
            _scene(audio_path=audio, visual=7.25),
            _timeline([]),
            tmp_path,
            workspace=workspace,
            runner=runner,
        )
        argv = runner.last
        assert argv[argv.index("-t") + 1] == "7.250000"


class TestTheConcatScript:
    def test_the_last_image_is_repeated_so_the_scene_is_not_a_frame_short(self, tmp_path):
        """The demuxer drops the final file's duration; the repeat is the fix."""
        scene = _scene(frames=((1.0, "a"), (2.0, "b")))
        script = compositor.concat_file(scene, tmp_path / "s.concat").read_text()
        lines = script.strip().splitlines()
        assert lines[-1].endswith("1.png'")
        assert lines[-2].endswith("1.png'") is False and lines[-2] == "duration 2.000000"
        assert lines.count("duration 2.000000") == 1

    def test_every_state_gets_its_own_duration(self, tmp_path):
        scene = _scene(frames=((1.5, "a"), (2.5, "b")))
        text = compositor.concat_file(scene, tmp_path / "s.concat").read_text()
        assert "duration 1.500000" in text and "duration 2.500000" in text


class TestNothingUnchangedIsEncodedTwice:
    def test_the_second_compile_comes_from_the_store(self, tmp_path, workspace, runner, audio):
        scene, timeline = _scene(audio_path=audio), _timeline([])
        out = tmp_path / "01_scene.mp4"

        def write_output(argv, kwargs):
            out.write_bytes(b"mp4")

        runner.on_call = write_output
        compositor.render_scene(scene, timeline, tmp_path, workspace=workspace, runner=runner)
        assert len(runner.calls) == 1

        out.unlink()
        recorder = Recorder()
        compositor.render_scene(
            scene, timeline, tmp_path, workspace=workspace, runner=runner, reporter=recorder
        )
        assert len(runner.calls) == 1, "the second call must come from the store"
        assert out.read_bytes() == b"mp4"
        assert recorder.lines == [(HIT, "scene video 01_scene")]

    def test_a_changed_frame_duration_re_encodes(self, tmp_path, workspace, runner, audio):
        timeline = _timeline([])
        out = tmp_path / "01_scene.mp4"
        runner.on_call = _writes(out, b"mp4")

        compositor.render_scene(
            _scene(audio_path=audio, frames=((1.0, "a"),)),
            timeline,
            tmp_path,
            workspace=workspace,
            runner=runner,
        )
        compositor.render_scene(
            _scene(audio_path=audio, frames=((1.5, "a"),)),
            timeline,
            tmp_path,
            workspace=workspace,
            runner=runner,
        )
        assert len(runner.calls) == 2

    def test_a_changed_voice_re_encodes(self, tmp_path, workspace, runner, audio):
        timeline = _timeline([])
        out = tmp_path / "01_scene.mp4"
        runner.on_call = _writes(out, b"mp4")

        compositor.render_scene(
            _scene(audio_path=audio), timeline, tmp_path, workspace=workspace, runner=runner
        )
        audio.write_bytes(b"a different take")
        compositor.render_scene(
            _scene(audio_path=audio), timeline, tmp_path, workspace=workspace, runner=runner
        )
        assert len(runner.calls) == 2

    def test_a_cold_encode_says_how_many_states_it_is_drawing_together(
        self, tmp_path, workspace, runner, audio
    ):
        recorder = Recorder()
        compositor.render_scene(
            _scene(audio_path=audio, frames=((1.0, "a"), (1.0, "b"))),
            _timeline([]),
            tmp_path,
            workspace=workspace,
            runner=runner,
            reporter=recorder,
        )
        assert recorder.lines == [(MISS, "scene video 01_scene (2 states)")]


class TestTheWebmIsCachedOnTheVideoItCameFrom:
    def test_a_rebuild_that_changed_nothing_does_not_re_encode(self, tmp_path, workspace, runner):
        source = tmp_path / "in.mp4"
        source.write_bytes(b"pretend this is a video")
        destination = tmp_path / "out.webm"
        runner.on_call = _writes(destination, b"webm")

        compositor.transcode_webm(source, destination, workspace=workspace, runner=runner)
        assert len(runner.calls) == 1

        destination.unlink()
        compositor.transcode_webm(source, destination, workspace=workspace, runner=runner)
        assert len(runner.calls) == 1
        assert destination.read_bytes() == b"webm"

    def test_a_changed_video_re_encodes(self, tmp_path, workspace, runner):
        source = tmp_path / "in.mp4"
        destination = tmp_path / "out.webm"
        runner.on_call = _writes(destination, b"webm")

        source.write_bytes(b"one")
        compositor.transcode_webm(source, destination, workspace=workspace, runner=runner)
        source.write_bytes(b"two")
        compositor.transcode_webm(source, destination, workspace=workspace, runner=runner)
        assert len(runner.calls) == 2

    def test_the_encoder_is_told_it_may_share_the_machine(self, tmp_path, workspace, runner):
        source = tmp_path / "in.mp4"
        source.write_bytes(b"x")
        destination = tmp_path / "out.webm"
        runner.on_call = _writes(destination, b"webm")
        compositor.transcode_webm(
            source, destination, workspace=workspace, runner=runner, threads=3
        )
        assert "-threads" in runner.last and "3" in runner.last

    def test_progress_is_reported_both_ways(self, tmp_path, workspace, runner):
        source = tmp_path / "in.mp4"
        source.write_bytes(b"x")
        destination = tmp_path / "out.webm"
        runner.on_call = _writes(destination, b"webm")
        cold, warm = Recorder(), Recorder()
        compositor.transcode_webm(
            source, destination, workspace=workspace, runner=runner, reporter=cold
        )
        compositor.transcode_webm(
            source, destination, workspace=workspace, runner=runner, reporter=warm
        )
        assert cold.lines == [(MISS, "webm (VP9/Opus)")]
        assert warm.lines == [(HIT, "webm (VP9/Opus)")]


class TestParallelEncodingMustNotReorderTheFilm:
    def test_scenes_come_back_in_timeline_order_however_they_finish(self, tmp_path):
        import random

        scenes = [_scene(i) for i in range(1, 9)]
        timeline = _timeline(scenes)

        def fake(scene, _timeline, work_dir, *, reporter, threads=0):
            random.Random(scene.id).random()  # noqa: S311 - finishing out of order, not crypto
            reporter.cache(MISS, f"scene video {scene.id}")
            return work_dir / f"{scene.id}.mp4"

        paths = compositor.render_scenes(scenes, timeline, tmp_path, workers=4, render=fake)
        assert [p.stem for p in paths] == [s.id for s in scenes]

    def test_progress_is_replayed_in_scene_order(self, tmp_path):
        scenes = [_scene(i) for i in range(1, 5)]
        recorder = Recorder()

        def fake(scene, _timeline, work_dir, *, reporter, threads=0):
            reporter.cache(HIT, f"scene video {scene.id}")
            return work_dir / f"{scene.id}.mp4"

        compositor.render_scenes(
            scenes, _timeline(scenes), tmp_path, reporter=recorder, workers=4, render=fake
        )
        assert [what.split()[-1] for _, what in recorder.lines] == [s.id for s in scenes]

    def test_one_worker_is_the_serial_path_and_gets_the_machine(self, tmp_path):
        seen = {}

        def fake(scene, _timeline, work_dir, *, reporter, threads=0):
            seen["threads"] = threads
            return work_dir / f"{scene.id}.mp4"

        scenes = [_scene(1)]
        compositor.render_scenes(scenes, _timeline(scenes), tmp_path, workers=1, render=fake)
        assert seen["threads"] >= 1, "a lone encoder should be told it may use the machine"

    def test_encoders_sharing_the_machine_are_each_given_a_share(self, tmp_path):
        seen = []

        def fake(scene, _timeline, work_dir, *, reporter, threads=0):
            seen.append(threads)
            return work_dir / f"{scene.id}.mp4"

        scenes = [_scene(i) for i in range(1, 5)]
        compositor.render_scenes(scenes, _timeline(scenes), tmp_path, workers=4, render=fake)
        assert all(t >= 1 for t in seen) and len(seen) == 4

    def test_a_film_with_no_scenes_encodes_nothing(self, tmp_path):
        def fake(scene, _timeline, work_dir, *, reporter, threads=0):
            raise AssertionError("nothing to encode")

        assert compositor.render_scenes([], _timeline([]), tmp_path, render=fake) == []


class TestJoiningAndProbing:
    def test_scenes_are_joined_by_stream_copy_never_re_encoded(self, tmp_path, workspace, runner):
        compositor.concat_scenes(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"],
            tmp_path / "out" / "film.mp4",
            tmp_path,
            runner=runner,
        )
        assert "-c" in runner.last and "copy" in runner.last
        assert not any(flag.startswith("libx264") for flag in runner.last)

    def test_the_listing_names_every_scene_in_order(self, tmp_path, runner):
        compositor.concat_scenes(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"],
            tmp_path / "film.mp4",
            tmp_path,
            runner=runner,
        )
        listing = (tmp_path / "scenes.concat").read_text().splitlines()
        assert listing[0].endswith("a.mp4'") and listing[1].endswith("b.mp4'")

    def test_probing_reports_what_the_container_holds_not_what_was_intended(self, tmp_path, runner):
        runner.stdout = '{"format": {"duration": "12.0"}}'
        assert compositor.probe(tmp_path / "a.mp4", runner=runner) == {
            "format": {"duration": "12.0"}
        }
        assert runner.last[0] == "ffprobe"
