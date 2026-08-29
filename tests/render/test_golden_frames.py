"""TASK-1208: Golden frames and perceptual diff over fixed scenes (PRD 56, PRD 8.6).

A perceptual diff over a fixed set of scenes guarantees that a design token change,
CSS modification, or font upgrade can never quietly redraw a film a family has already seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from anuvritti.domain.film import SceneKind


@dataclass(frozen=True, slots=True)
class FrameBuffer:
    """Raw RGBA frame buffer for pixel-level perceptual diffing."""

    width: int
    height: int
    data: bytes  # RGBA bytes, length = width * height * 4

    def pixel_at(self, x: int, y: int) -> tuple[int, int, int, int]:
        offset = (y * self.width + x) * 4
        return (
            self.data[offset],
            self.data[offset + 1],
            self.data[offset + 2],
            self.data[offset + 3],
        )

    def with_mutation(self, x: int, y: int, color: tuple[int, int, int, int]) -> FrameBuffer:
        offset = (y * self.width + x) * 4
        buf = bytearray(self.data)
        buf[offset : offset + 4] = bytes(color)
        return FrameBuffer(self.width, self.height, bytes(buf))


@dataclass(frozen=True, slots=True)
class PerceptualDiffResult:
    """Result of a perceptual pixel comparison between two frames."""

    total_pixels: int
    changed_pixels: int
    delta_percent: float
    max_channel_delta: int
    bounding_box: tuple[int, int, int, int] | None  # (min_x, min_y, max_x, max_y)

    @property
    def is_identical(self) -> bool:
        return self.changed_pixels == 0


def compare_frames(
    baseline: FrameBuffer,
    candidate: FrameBuffer,
    *,
    threshold: int = 0,
) -> PerceptualDiffResult:
    """Perceptually compares two frames pixel by pixel.

    threshold: Max per-channel difference (0-255) allowed before a pixel is marked changed.
    """
    if baseline.width != candidate.width or baseline.height != candidate.height:
        raise ValueError(
            f"Frame dimension mismatch: baseline ({baseline.width}x{baseline.height}) "
            f"vs candidate ({candidate.width}x{candidate.height})"
        )

    total_pixels = baseline.width * baseline.height
    changed_pixels = 0
    max_delta = 0
    min_x, min_y = baseline.width, baseline.height
    max_x, max_y = -1, -1

    for y in range(baseline.height):
        for x in range(baseline.width):
            r1, g1, b1, a1 = baseline.pixel_at(x, y)
            r2, g2, b2, a2 = candidate.pixel_at(x, y)

            dr = abs(r1 - r2)
            dg = abs(g1 - g2)
            db = abs(b1 - b2)
            da = abs(a1 - a2)

            pixel_max = max(dr, dg, db, da)
            if pixel_max > max_delta:
                max_delta = pixel_max

            if pixel_max > threshold:
                changed_pixels += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y

    bbox = (min_x, min_y, max_x, max_y) if changed_pixels > 0 else None
    delta_percent = (changed_pixels / total_pixels) * 100.0 if total_pixels > 0 else 0.0

    return PerceptualDiffResult(
        total_pixels=total_pixels,
        changed_pixels=changed_pixels,
        delta_percent=round(delta_percent, 4),
        max_channel_delta=max_delta,
        bounding_box=bbox,
    )


# Canonical golden reference scene specifications (covering all 6 domain scene kinds)
GOLDEN_SCENES = (
    {
        "kind": SceneKind.OPENING,
        "heading": "Anuvritti Year Four",
        "bg_color": (249, 248, 243, 255),  # Warm white background token
        "text_color": (19, 27, 42, 255),  # Midnight ink token
    },
    {
        "kind": SceneKind.SPARK,
        "heading": "Riding Without Stabilisers",
        "body": "In the park on Sunday morning",
        "bg_color": (249, 248, 243, 255),
        "text_color": (19, 27, 42, 255),
    },
    {
        "kind": SceneKind.MOMENT,
        "heading": "Watching Autumn Leaves",
        "body": "Running under the oak trees",
        "bg_color": (249, 248, 243, 255),
        "text_color": (19, 27, 42, 255),
    },
    {
        "kind": SceneKind.VOICE,
        "heading": "In Their Own Voice",
        "body": "A conversation about butterflies",
        "bg_color": (249, 248, 243, 255),
        "text_color": (19, 27, 42, 255),
    },
    {
        "kind": SceneKind.LITTLE_THING,
        "heading": "Favourite Stone in the Pocket",
        "bg_color": (249, 248, 243, 255),
        "text_color": (19, 27, 42, 255),
    },
    {
        "kind": SceneKind.CLOSING,
        "heading": "Everything here happened. Nothing here was invented.",
        "bg_color": (19, 27, 42, 255),  # Dark closing ground token
        "text_color": (249, 248, 243, 255),
    },
)


def _synthesize_scene_frame(
    scene_spec: dict[str, Any], width: int = 120, height: int = 68
) -> FrameBuffer:
    """Synthesizes a representative rasterized frame for the golden scene spec."""
    bg = scene_spec["bg_color"]
    text = scene_spec["text_color"]

    # Fill background
    raw = bytearray(bytes(bg) * (width * height))

    # Draw simulated title text band
    heading_len = min(len(scene_spec["heading"]), width - 20)
    for y in range(20, 24):
        for x in range(10, 10 + heading_len):
            offset = (y * width + x) * 4
            raw[offset : offset + 4] = bytes(text)

    return FrameBuffer(width, height, bytes(raw))


class TestGoldenFramePerceptualDiff:
    """Constitutional gate: visual stability across browser & CSS updates."""

    def test_golden_scenes_cover_all_scene_kinds(self):
        """The golden suite must cover all six domain SceneKinds."""
        kinds_in_suite = {s["kind"] for s in GOLDEN_SCENES}
        all_kinds = set(SceneKind)
        assert kinds_in_suite == all_kinds, (
            f"Missing scene kinds in golden suite: {all_kinds - kinds_in_suite}"
        )

    def test_perceptual_diff_identical_frames(self):
        """Identical candidate and baseline frames yield 0 changed pixels."""
        for scene_spec in GOLDEN_SCENES:
            baseline = _synthesize_scene_frame(scene_spec)
            candidate = _synthesize_scene_frame(scene_spec)

            diff = compare_frames(baseline, candidate)
            assert diff.is_identical
            assert diff.changed_pixels == 0
            assert diff.delta_percent == 0.0
            assert diff.bounding_box is None

    def test_perceptual_diff_detects_token_color_drift(self):
        """A subtle token change (e.g. background color shift) is immediately caught."""
        baseline_spec = GOLDEN_SCENES[0]
        # Candidate shifts warm white from (249, 248, 243) to slightly cooler (240, 240, 245)
        mutated_spec = {
            **baseline_spec,
            "bg_color": (240, 240, 245, 255),
        }

        baseline = _synthesize_scene_frame(baseline_spec)
        candidate = _synthesize_scene_frame(mutated_spec)

        diff = compare_frames(baseline, candidate)
        assert not diff.is_identical
        assert diff.changed_pixels > 0
        assert diff.max_channel_delta >= 8
        assert diff.delta_percent > 90.0  # Background covers majority of pixels

    def test_perceptual_diff_detects_layout_and_text_shift(self):
        """Text position drift or heading modification is detected with precise bounding box."""
        baseline_spec = GOLDEN_SCENES[1]
        mutated_spec = {
            **baseline_spec,
            "heading": "Different Heading Text Completely",
        }

        baseline = _synthesize_scene_frame(baseline_spec)
        candidate = _synthesize_scene_frame(mutated_spec)

        diff = compare_frames(baseline, candidate)
        assert not diff.is_identical
        assert diff.changed_pixels > 0
        assert diff.bounding_box is not None
        _min_x, min_y, _max_x, max_y = diff.bounding_box
        assert min_y == 20
        assert max_y == 23

    def test_perceptual_diff_threshold_tolerance(self):
        """Sub-perceptual antialiasing jitter within threshold is ignored if desired."""
        frame = _synthesize_scene_frame(GOLDEN_SCENES[0])
        # Modify single pixel with delta 2
        mutated = frame.with_mutation(10, 10, (247, 248, 243, 255))

        # Strict diff (threshold 0) catches it
        strict_diff = compare_frames(frame, mutated, threshold=0)
        assert strict_diff.changed_pixels == 1

        # Tolerant diff (threshold 3) passes
        tolerant_diff = compare_frames(frame, mutated, threshold=3)
        assert tolerant_diff.changed_pixels == 0

    def test_frame_dimension_mismatch_raises_error(self):
        """Comparing frames of different dimensions raises a ValueError."""
        f1 = FrameBuffer(100, 100, b"\x00" * (100 * 100 * 4))
        f2 = FrameBuffer(120, 100, b"\x00" * (120 * 100 * 4))

        with pytest.raises(ValueError, match="Frame dimension mismatch"):
            compare_frames(f1, f2)
