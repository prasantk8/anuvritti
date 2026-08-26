"""The same picture is drawn once, and a warm compile draws nothing."""

from __future__ import annotations

import pytest

from filmkit import browser
from filmkit.browser import FrameFarm, Shot, frame_key
from filmkit.reporting import Recorder

THEME = {"font_size_px": 22, "background": "#000", "foreground": "#fff"}


def _shot(tmp_path, name, html):
    return Shot(
        destination=tmp_path / "out" / f"{name}.png",
        html=html,
        key_payload={"scene": "01_a", "state": name},
        duration_sec=1.0,
        label=name,
    )


class TestAFrameIsItsOwnContentAddress:
    def test_the_same_markup_is_the_same_frame(self):
        assert frame_key("<p>x</p>", {"s": "a"}, 1920, 1080, THEME) == frame_key(
            "<p>x</p>", {"s": "a"}, 1920, 1080, THEME
        )

    @pytest.mark.parametrize(
        "html,payload,width,height,theme",
        [
            ("<p>y</p>", {"s": "a"}, 1920, 1080, THEME),
            ("<p>x</p>", {"s": "b"}, 1920, 1080, THEME),
            ("<p>x</p>", {"s": "a"}, 1280, 1080, THEME),
            ("<p>x</p>", {"s": "a"}, 1920, 720, THEME),
            ("<p>x</p>", {"s": "a"}, 1920, 1080, {**THEME, "font_size_px": 23}),
        ],
    )
    def test_any_change_that_changes_the_picture_changes_the_key(
        self, html, payload, width, height, theme
    ):
        base = frame_key("<p>x</p>", {"s": "a"}, 1920, 1080, THEME)
        assert frame_key(html, payload, width, height, theme) != base

    def test_the_renderer_is_part_of_the_key(self):
        """A cache is only shareable between machines if it says who drew it."""
        base = frame_key("<p>x</p>", {}, 1920, 1080, THEME)
        assert frame_key("<p>x</p>", {}, 1920, 1080, THEME, renderer="other") != base


class TestNothingIsDrawnTwice:
    def test_a_fully_cached_compile_never_starts_a_browser(self, tmp_path, workspace, painter):
        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, workers=4, painter=painter)
        shots = [_shot(tmp_path, "a", "<p>a</p>"), _shot(tmp_path, "b", "<p>b</p>")]
        for shot in shots:
            (farm.frame_cache / f"{farm.key_for(shot)}.png").write_bytes(b"png")

        stats = farm.render(shots)

        assert stats == {"hits": 2, "misses": 0, "workers": 1}
        assert painter.documents == [], "a warm compile must not paint"
        assert all(shot.destination.read_bytes() == b"png" for shot in shots)

    def test_an_identical_state_in_two_scenes_is_drawn_once(self, tmp_path, workspace, painter):
        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, workers=4, painter=painter)
        shots = [
            Shot(tmp_path / "out" / "a.png", "<p>same</p>", {"state": "s"}, 1.0, "s"),
            Shot(tmp_path / "out" / "b.png", "<p>same</p>", {"state": "s"}, 1.0, "s"),
        ]

        stats = farm.render(shots)

        assert len(painter.documents) == 1, "the same picture must not be painted twice"
        assert stats["misses"] == 1
        assert all(shot.destination.is_file() for shot in shots)

    def test_a_second_compile_reuses_the_first_one_s_frames(self, tmp_path, workspace, painter):
        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, painter=painter)
        farm.render([_shot(tmp_path, "a", "<p>a</p>")])
        stats = farm.render([_shot(tmp_path, "a", "<p>a</p>")])
        assert stats["hits"] == 1
        assert len(painter.documents) == 1

    def test_work_is_spread_round_robin_so_no_lane_gets_all_the_heavy_frames(
        self, tmp_path, workspace, painter
    ):
        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, workers=3, painter=painter)
        farm.render([_shot(tmp_path, f"s{i}", f"<p>{i}</p>") for i in range(9)])
        assert sorted(painter.chunks) == [3, 3, 3]

    def test_more_lanes_than_work_does_not_start_idle_browsers(self, tmp_path, workspace, painter):
        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, workers=8, painter=painter)
        stats = farm.render([_shot(tmp_path, "a", "<p>a</p>")])
        assert painter.chunks == [1] and stats["workers"] == 1

    def test_a_painter_that_fails_fails_the_compile(self, tmp_path, workspace):
        class Broken:
            def __call__(self, width, height, jobs):
                raise RuntimeError("no browser here")

        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, workers=2, painter=Broken())
        with pytest.raises(RuntimeError, match="no browser here"):
            farm.render([_shot(tmp_path, "a", "<p>a</p>"), _shot(tmp_path, "b", "<p>b</p>")])


class TestTheDocumentHookIsTheOnlyPlaceAPageShellBelongs:
    def test_by_default_the_markup_already_is_the_document(self, tmp_path, workspace, painter):
        farm = FrameFarm(1920, 1080, THEME, workspace=workspace, painter=painter)
        farm.render([_shot(tmp_path, "a", "<p>a</p>")])
        assert painter.documents == ["<p>a</p>"]

    def test_a_caller_with_a_stylesheet_wraps_here(self, tmp_path, workspace, painter):
        class Wrapped(FrameFarm):
            def document(self, html):
                return f"<style>body{{margin:0}}</style>{html}"

        farm = Wrapped(1920, 1080, THEME, workspace=workspace, painter=painter)
        farm.render([_shot(tmp_path, "a", "<p>a</p>")])
        assert painter.documents == ["<style>body{margin:0}</style><p>a</p>"]

    def test_the_shell_is_not_in_the_key_so_the_caller_owns_that_decision(
        self, tmp_path, workspace, painter
    ):
        """Whatever wraps the markup must be reflected in the theme or the payload."""

        class Wrapped(FrameFarm):
            def document(self, html):
                return f"<shell>{html}</shell>"

        plain = FrameFarm(1920, 1080, THEME, workspace=workspace, painter=painter)
        wrapped = Wrapped(1920, 1080, THEME, workspace=workspace, painter=painter)
        shot = _shot(tmp_path, "a", "<p>a</p>")
        assert plain.key_for(shot) == wrapped.key_for(shot)


def test_progress_names_how_many_browsers_are_starting(tmp_path, workspace, painter):
    recorder = Recorder()
    farm = FrameFarm(1920, 1080, THEME, workspace=workspace, workers=2, painter=painter)
    farm.render([_shot(tmp_path, "a", "<p>a</p>"), _shot(tmp_path, "b", "<p>b</p>")], recorder)
    assert recorder.lines == [("RENDER", "2 frames across 2 browsers")]


def test_a_single_browser_is_said_in_the_singular(tmp_path, workspace, painter):
    recorder = Recorder()
    farm = FrameFarm(1920, 1080, THEME, workspace=workspace, painter=painter)
    farm.render([_shot(tmp_path, "a", "<p>a</p>")], recorder)
    assert recorder.lines == [("RENDER", "1 frames across 1 browser")]


def test_the_chromium_flags_that_make_a_shared_cache_trustworthy_are_pinned():
    """Colour profile, hinting and LCD text each make identical markup differ."""
    assert "--force-color-profile=srgb" in browser.CHROMIUM_ARGS
    assert "--disable-lcd-text" in browser.CHROMIUM_ARGS
    assert "--font-render-hinting=none" in browser.CHROMIUM_ARGS
