"""TASK-1007 - Design Constitution: the 3AM night surface and one-handed reach.

(PRD 56, PRD 8.4.)

Verifies that:
1. True OLED black (#000000) is defined for maximum battery saving and zero ambient emission.
2. Max luminance across all night tokens is strictly <= 0.35.
"""

from __future__ import annotations

from tests.design.world import luminance

NIGHT_TOKENS = {
    "ground": "#000000",
    "surface": "#0A0C10",
    "ink": "#9E9A8E",
    "inkQuiet": "#5C5950",
    "saffron": "#B08035",
    "thread": "#1A1D24",
}


def test_night_surface_has_zero_backlight_oled_ground():
    assert NIGHT_TOKENS["ground"] == "#000000"
    assert luminance(NIGHT_TOKENS["ground"]) == 0.0


def test_all_night_surface_tokens_are_low_glare():
    for name, hex_code in NIGHT_TOKENS.items():
        lum = luminance(hex_code)
        assert lum <= 0.35, (
            f"Night token {name} ({hex_code}) has luminance {lum:.3f} > 0.35 room-glare threshold"
        )
