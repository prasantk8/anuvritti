"""Reads the emitted design language, and refuses to read a stale one.

`packages/world` is the source of truth for the interface. These helpers load what it
emitted, so the Python gate holds the *shipped* tokens to the constitution rather than
a copy that drifted.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORLD = ROOT / "packages" / "world"
DIST = WORLD / "dist"


class StaleWorldError(RuntimeError):
    """The emitted tokens are older than their source."""


@cache
def tokens() -> dict:
    emitted = DIST / "tokens.json"
    if not emitted.exists():
        raise StaleWorldError(
            "packages/world has not been built - run `npm --prefix packages/world run build`"
        )
    newest_source = max(p.stat().st_mtime for p in (WORLD / "src").rglob("*.ts"))
    if newest_source > emitted.stat().st_mtime:
        raise StaleWorldError(
            "packages/world/src is newer than dist - the interface and its tests disagree. "
            "Run `npm --prefix packages/world run build`."
        )
    return json.loads(emitted.read_text())


@cache
def world_css() -> str:
    return (DIST / "world.css").read_text()


def colors() -> list[dict]:
    return tokens()["colors"]


def palette(theme: str) -> dict[str, str]:
    return {c["name"]: c[theme] for c in colors()}


# -- Colour arithmetic, implemented here rather than imported. --------------------
# packages/world tests its palette with its own TypeScript implementation. This is a
# second, independent one: two implementations that agree are evidence, one is a claim.


def _channels(hex_value: str) -> tuple[float, float, float]:
    h = hex_value.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(hex_value: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in _channels(hex_value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def chroma(hex_value: str) -> float:
    r, g, b = _channels(hex_value)
    return max(r, g, b) - min(r, g, b)


def hue(hex_value: str) -> float:
    r, g, b = _channels(hex_value)
    hi, lo = max(r, g, b), min(r, g, b)
    d = hi - lo
    if d == 0:
        return 0.0
    if hi == r:
        h = ((g - b) / d) % 6
    elif hi == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60
