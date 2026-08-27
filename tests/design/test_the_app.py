"""TASK-714: the app's colour and language boundaries, read from shipped source."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "anuvritti"
SAID = APP / "src" / "said.ts"
SCREENS = tuple((APP / "app").glob("*.tsx")) + tuple((APP / "src" / "components").glob("*.tsx"))
VOICE_COLOUR_HOMES = {
    Path("src/components/HoldToTalk.tsx"),
    Path("src/components/VoiceNote.tsx"),
}
ASSUMED_PEOPLE = re.compile(
    r"\b(?:he|him|his|she|her|hers|mum|mom|mama|dad|papa|father|mother|son|daughter)\b",
    re.I,
)


def _code(source: str) -> str:
    """Remove comments: design rationale may name the failure it prevents."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//.*", "", source)


def _saffron_offenders(sources: dict[Path, str]) -> set[Path]:
    return {
        path
        for path, source in sources.items()
        if re.search(r"world\.color(?:\[.[\"']saffron(?:-wash)?[\"'].\]|\.saffron)", _code(source))
        and path not in VOICE_COLOUR_HOMES
    }


def _elapsed_copy(source: str) -> list[str]:
    return re.findall(r"\b\d+\s+days?\b", _code(source), flags=re.I)


def _assumptions(source: str) -> list[str]:
    return ASSUMED_PEOPLE.findall(_code(source))


def _literal_screen_copy(source: str) -> list[str]:
    code = _code(source)
    between_tags = re.findall(r"<Text\b[^>]*>\s*([^\s<{][^<]*?)\s*</Text>", code, flags=re.S)
    literal_props = re.findall(
        r"(?:accessibilityHint|accessibilityLabel|label|placeholder)=[\"']([^\"']+)[\"']",
        code,
    )
    return [value.strip() for value in (*between_tags, *literal_props) if value.strip()]


def test_saffron_is_only_a_persons_voice_on_the_waveform_and_player():
    sources = {path.relative_to(APP): path.read_text() for path in APP.rglob("*.tsx")}
    assert not _saffron_offenders(sources)
    assert {
        path for path, source in sources.items() if "world.color.saffron" in _code(source)
    } == VOICE_COLOUR_HOMES


def test_no_screen_can_say_an_exact_number_of_days():
    offenders = {
        path.relative_to(APP): _elapsed_copy(path.read_text())
        for path in (*SCREENS, SAID)
        if _elapsed_copy(path.read_text())
    }
    assert not offenders


def test_app_copy_assumes_no_pronoun_or_family_relationship():
    assert not _assumptions(SAID.read_text())


def test_every_screen_gets_its_words_from_said():
    offenders = {
        path.relative_to(APP): _literal_screen_copy(path.read_text())
        for path in SCREENS
        if _literal_screen_copy(path.read_text())
    }
    assert not offenders
    word_bearing = {
        APP / "app" / "index.tsx",
        APP / "app" / "pair.tsx",
        APP / "app" / "vault.tsx",
        APP / "src" / "components" / "HoldToTalk.tsx",
        APP / "src" / "components" / "VoiceNote.tsx",
        APP / "src" / "components" / "Spark.tsx",
    }
    assert all(
        'from "../src/said.ts"' in path.read_text() for path in word_bearing if "/app/" in str(path)
    )
    assert all(
        'from "../said.ts"' in path.read_text()
        for path in word_bearing
        if "/components/" in str(path)
    )


def test_each_scanner_catches_the_line_it_exists_to_forbid():
    assert _saffron_offenders({Path("app/index.tsx"): "world.color.saffron"})
    assert _elapsed_copy('const status = "12 days ago"') == ["12 days"]
    assert _assumptions('const prompt = "What did his dad say?"') == ["his", "dad"]
    assert _literal_screen_copy('<Text accessibilityLabel="A label">Hardcoded</Text>') == [
        "Hardcoded",
        "A label",
    ]
