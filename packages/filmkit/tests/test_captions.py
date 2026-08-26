"""Captions come from the same words the voice said, over the moment it said them."""

from __future__ import annotations

from filmkit import captions
from filmkit.timeline import FrameEntry, SceneEntry, Timeline


def _timeline(*scenes):
    return Timeline("p", 60, 1920, 1080, list(scenes))


def _scene(scene_id, narration, audio, visual):
    return SceneEntry(
        id=scene_id,
        type="card",
        start_sec=0.0,
        audio_path="a.mp3",
        audio_duration_sec=audio,
        visual_duration_sec=visual,
        frames=[FrameEntry("a.png", visual, "s")],
        narration=narration,
    )


def test_a_cue_covers_the_speech_and_not_the_silence():
    timeline = _timeline(_scene("01_a", "hello", audio=4.0, visual=6.0))
    ((start, end, text),) = captions.cues(timeline)
    assert (start, end, text) == (1.0, 5.0, "hello")


def test_cues_advance_by_the_visual_length_not_the_audio_one():
    timeline = _timeline(
        _scene("01_a", "one", audio=4.0, visual=6.0),
        _scene("02_b", "two", audio=2.0, visual=4.0),
    )
    second = captions.cues(timeline)[1]
    assert second[0] == 7.0 and second[1] == 9.0


def test_a_scene_with_no_padding_starts_its_cue_immediately():
    timeline = _timeline(_scene("01_a", "hello", audio=5.0, visual=5.0))
    assert captions.cues(timeline)[0][0] == 0.0


def test_audio_longer_than_its_scene_does_not_produce_a_negative_lead_in():
    """The timeline reports that as truncation; captions must not compound it."""
    timeline = _timeline(_scene("01_a", "hello", audio=8.0, visual=5.0))
    assert captions.cues(timeline)[0][0] == 0.0


def test_srt_is_numbered_and_uses_commas(tmp_path):
    timeline = _timeline(
        _scene("01_a", "one", audio=4.0, visual=6.0),
        _scene("02_b", "two", audio=2.0, visual=4.0),
    )
    text = captions.write_srt(timeline, tmp_path / "a.srt").read_text()
    assert text.startswith("1\n00:00:01,000 --> 00:00:05,000\none\n")
    assert "2\n00:00:07,000 --> 00:00:09,000\ntwo\n" in text


def test_vtt_declares_itself_and_uses_dots(tmp_path):
    timeline = _timeline(_scene("01_a", "one", audio=4.0, visual=6.0))
    text = captions.write_vtt(timeline, tmp_path / "a.vtt").read_text()
    assert text.startswith("WEBVTT\n")
    assert "00:00:01.000 --> 00:00:05.000" in text


def test_a_long_film_crosses_the_hour_correctly(tmp_path):
    timeline = _timeline(_scene("01_a", "one", audio=3700.0, visual=3700.0))
    text = captions.write_srt(timeline, tmp_path / "a.srt").read_text()
    assert "01:01:40,000" in text


def test_a_rounding_carry_does_not_produce_a_thousand_milliseconds(tmp_path):
    timeline = _timeline(_scene("01_a", "one", audio=0.9999, visual=0.9999))
    text = captions.write_srt(timeline, tmp_path / "a.srt").read_text()
    assert "00:00:01,000" in text and ",1000" not in text


def test_an_empty_film_produces_an_empty_track(tmp_path):
    assert captions.write_srt(_timeline(), tmp_path / "a.srt").read_text() == ""
    assert captions.write_vtt(_timeline(), tmp_path / "a.vtt").read_text() == "WEBVTT\n"
