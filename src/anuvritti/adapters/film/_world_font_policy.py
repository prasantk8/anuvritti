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
WORLD_FONT_FILES: Final[dict[str, str]] = {
    "ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2": (
        "3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e"
    ),
    "ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2": (
        "0717336fb31fcdcde4b8deb3675bb4a0f7f6d484864afcd6751ac29975962203"
    ),
    "newsreader/files/newsreader-latin-400-normal.woff2": (
        "e66067814f1c672d33a457e4f4d102c818b481420e2234cf685ebdbf2f443904"
    ),
    "noto-naskh-arabic/files/noto-naskh-arabic-arabic-400-normal.woff2": (
        "9cc2d2e90f7b51904468558b4ed529de8a8206497c8edb5e33122bd077e0158c"
    ),
    "noto-sans-arabic/files/noto-sans-arabic-arabic-400-normal.woff2": (
        "4e2ca0745c908761dc5c5db951662873887c59366fa1a5693ad22c0864abf1bd"
    ),
    "noto-sans-arabic/files/noto-sans-arabic-arabic-500-normal.woff2": (
        "38599e3046a0ceeae9d10fb9c282424d16b7a05f0838478fabe27908fc922722"
    ),
    "noto-sans-devanagari/files/noto-sans-devanagari-devanagari-400-normal.woff2": (
        "f86f14cbd1004f5795689ee9cc70d5d87d915f5135b30283525c1c7b8f0eb192"
    ),
    "noto-sans-devanagari/files/noto-sans-devanagari-devanagari-500-normal.woff2": (
        "c9e45ff29dddc46bdb85b0cb97922fde980ae2fcafadee4498ff25bd0448292f"
    ),
    "noto-serif-devanagari/files/noto-serif-devanagari-devanagari-400-normal.woff2": (
        "e64b3b73131abb4074d4b22453bffe54fe8973fa0ea98a32504570df647b2a0a"
    ),
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
