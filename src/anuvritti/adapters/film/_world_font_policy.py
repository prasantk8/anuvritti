"""Generated from packages/world/scenes/fonts.ts. Do not edit by hand."""

from typing import Final

WORLD_BUNDLE_NAME: Final = "@anuvritti/world"
WORLD_BUNDLE_VERSION: Final = "0.1.0"
WORLD_FONT_PACKAGES: Final[dict[str, str]] = {
    "@fontsource/ibm-plex-sans": "5.3.0",
    "@fontsource/newsreader": "5.3.0",
    "@fontsource/noto-naskh-arabic": "5.3.0",
    "@fontsource/noto-sans-arabic": "5.3.0",
    "@fontsource/noto-sans-devanagari": "5.3.0",
    "@fontsource/noto-serif-devanagari": "5.3.0",
}
SCRIPT_ORDER: Final[tuple[str, ...]] = (
    "Latin",
    "Arabic",
    "Devanagari",
)
COMMON_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (9, 13),
    (32, 126),
    (160, 191),
    (8192, 8303),
)
SCRIPT_RANGES: Final[dict[str, tuple[tuple[int, int], ...]]] = {
    "Latin": (
        (9, 13),
        (32, 126),
        (160, 191),
        (8192, 8303),
        (192, 591),
        (768, 879),
        (7680, 7935),
    ),
    "Arabic": (
        (1536, 1791),
        (1872, 1919),
        (2160, 2207),
        (2208, 2303),
    ),
    "Devanagari": (
        (2304, 2431),
        (7376, 7423),
    ),
}
