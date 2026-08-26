"""Concurrency changes the speed, not the story."""

from __future__ import annotations

from filmkit.reporting import HIT, MISS, Recorder, Silent


def test_silent_says_nothing_and_returns_nothing(capsys):
    assert Silent().cache(HIT, "x") is None
    assert capsys.readouterr().out == ""


def test_a_recorder_replays_in_the_order_it_was_told():
    recorder = Recorder()
    recorder.cache(MISS, "b")
    recorder.cache(HIT, "a")

    replayed = Recorder()
    recorder.replay(replayed)
    assert replayed.lines == [(MISS, "b"), (HIT, "a")]


def test_anything_with_a_cache_method_is_a_reporter():
    """Structural, not inherited - a host's own console qualifies as it is."""

    class Console:
        def __init__(self):
            self.seen = []

        def cache(self, verb, what):
            self.seen.append((verb, what))

    console = Console()
    Recorder().replay(console)
    recorder = Recorder()
    recorder.cache(HIT, "x")
    recorder.replay(console)
    assert console.seen == [(HIT, "x")]
