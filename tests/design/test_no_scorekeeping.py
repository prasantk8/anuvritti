"""PRD 8.5, 47, 53 - the constitution, enforced in pixels.

`tests/constitution/test_no_guilt.py` proves the product will not *say* anything that
blames a parent. It cannot see the interface. A badge with a number in it says the same
thing without using a word, so the same boundary has to hold one layer out.

These tests read what `packages/world` actually emitted, not a description of it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from anuvritti.domain.return_engine import describe_elapsed
from tests.design.world import (
    DIST,
    chroma,
    colors,
    contrast,
    hue,
    palette,
    tokens,
    world_css,
)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SPECIMEN = ROOT / "packages" / "world" / "specimen" / "index.html"
THEMES = ("light", "dark")

#: Mechanics that turn a family's material into a performance being marked.
SCOREKEEPING = (
    "streak",
    "badge",
    "leaderboard",
    "points",
    "level up",
    "completion rate",
    "unread count",
    "progress bar",
    "trophy",
    "milestone reached",
)

#: Interface vocabulary that measures a parent rather than helping them.
TALLY_FIELDS = (
    "days_ago",
    "days_since",
    "elapsed_days",
    "age_days",
    "unread",
    "pending_count",
    "streak",
    "completion",
    "score_display",
)


def _interface_text() -> str:
    """The interface as a reader sees it, with declared counter-examples removed.

    The specimen shows what the product refuses to render, marked as such. Those are
    the opposite of a violation, so they are excluded rather than flagged.
    """
    html = SPECIMEN.read_text()
    html = re.sub(r"<span[^>]*data-counterexample[^>]*>.*?</span>", "", html, flags=re.S)
    return re.sub(r"const SAID = \[.*?\];", "", html, flags=re.S)


class TestThePaletteKeepsNoScore:
    def test_no_token_names_a_thing_the_constitution_forbids(self):
        for token in colors():
            for word in (
                "overdue",
                "late",
                "streak",
                "score",
                "badge",
                "danger",
                "alert",
                "warning",
            ):
                assert word not in token["name"], (
                    f"PRD 47: the palette offers {token['name']!r}, "
                    "which is a colour for a concept the product does not have"
                )

    def test_every_colour_declares_what_it_means(self):
        """A colour without a stated meaning is a colour that will be reused for anything."""
        for token in colors():
            assert len(token["meaning"]) > 30, token["name"]
            assert token["role"] in {
                "ground",
                "surface",
                "ink",
                "structure",
                "voice",
                "destructive",
            }

    def test_there_is_exactly_one_red_and_it_means_erased(self):
        reddish = [
            t["name"]
            for t in colors()
            if any(
                chroma(t[th]) > 0.25 and (hue(t[th]) <= 18 or hue(t[th]) >= 344) for th in THEMES
            )
        ]
        assert reddish == ["unmade"], (
            "PRD 8.5: urgency colour is reserved for what cannot be undone. "
            "Lateness is not urgent, and a child is never an error state."
        )
        assert next(t for t in colors() if t["name"] == "unmade")["role"] == "destructive"

    def test_the_voice_colour_only_ever_means_a_person_spoke(self):
        saffron = [t for t in colors() if t["name"].startswith("saffron")]
        assert saffron, "the voice colour is missing entirely"
        assert all(t["role"] == "voice" for t in saffron)


class TestLegibilityInBothThemes:
    """An independent implementation of the same check packages/world runs on itself.

    Two implementations that agree are evidence. One is a claim.
    """

    @pytest.mark.parametrize("theme", THEMES)
    def test_text_is_legible_on_every_ground_it_sits_on(self, theme):
        p = palette(theme)
        failures = []
        for token in colors():
            for ground in token.get("readableOn") or ():
                ratio = contrast(token[theme], p[ground])
                if ratio < token.get("minContrast", 4.5):
                    failures.append(f"{token['name']} on {ground} ({theme}): {ratio:.2f}")
        assert not failures, failures

    def test_no_colour_is_theme_blind(self):
        for token in colors():
            assert token["light"].upper() != token["dark"].upper(), token["name"]


class TestElapsedTimeIsNeverANumber:
    def test_precision_is_deliberately_lost_as_time_passes(self):
        """PRD 8.5. "243 days ago" is what a database would say to a father.

        Past a fortnight the exact figure must be gone - not rounded in the copy, but
        genuinely absent from the string, so no interface can recover it.
        """
        for days in range(14, 4000):
            said = describe_elapsed(days)
            assert str(days) not in said, (
                f"describe_elapsed({days}) leaked the exact count: {said!r}"
            )

    def test_the_wire_carries_no_tally_a_parent_could_read_as_a_verdict(self):
        """Anything the HTTP edge can serialise is something an interface can render."""
        schemas = (SRC / "anuvritti" / "interfaces" / "http" / "schemas.py").read_text()
        tree = ast.parse(schemas)
        fields = {
            node.target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        offenders = sorted(f for f in fields if any(bad in f.lower() for bad in TALLY_FIELDS))
        assert not offenders, f"PRD 53: these reach a client as numbers to display: {offenders}"

    def test_the_interface_renders_no_raw_elapsed_count(self):
        text = _interface_text()
        for pattern in (r"\d+\s+days ago", r"\d+\s+hours ago", r"\bday \d+\b"):
            assert not re.search(pattern, text, re.I), f"interface renders {pattern!r} literally"


def _words(name: str) -> str:
    """Normalise an identifier or a UI string to its component words.

    `current_streak` and `currentStreak` both become "current streak", so a forbidden
    term is matched on word boundaries that actually exist. A plain `\\bstreak` regex
    misses `current_streak` entirely - `_` is a word character, so there is no boundary
    there - while a plain substring search flags `endpoints` for containing "points".
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return " ".join(re.split(r"[^a-zA-Z0-9]+", spaced)).strip().lower()


def _implemented_vocabulary(path: Path) -> set[str]:
    """Names the code actually uses, plus strings it could show a person.

    Deliberately *not* a text search. `presence.py` opens by saying the product has no
    streak and no completion rate; a document declaring a non-goal is the opposite of a
    violation. Comments never enter the AST, and docstrings are dropped here, so what
    remains is what the code does rather than what it says about itself.
    """
    tree = ast.parse(path.read_text())
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            found.add(node.name)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node not in docstrings
        ):
            found.add(node.value)
    return {_words(f) for f in found}


class TestNothingAnywhereKeepsScore:
    @pytest.mark.parametrize("word", SCOREKEEPING)
    def test_no_module_implements_it(self, word):
        offenders = [
            path.relative_to(ROOT)
            for path in SRC.rglob("*.py")
            if any(
                re.search(rf"\b{re.escape(word)}\b", name) for name in _implemented_vocabulary(path)
            )
        ]
        assert not offenders, f"PRD 47 forbids {word!r}; implemented in {offenders}"

    @pytest.mark.parametrize("word", SCOREKEEPING)
    def test_the_interface_never_shows_it(self, word):
        assert not re.search(rf"\b{re.escape(word)}\b", _words(_interface_text())), (
            f"PRD 47 forbids {word!r} in the interface"
        )

    def test_the_interface_shows_no_notification_dot(self):
        text = _interface_text().lower()
        for marker in ("badge", "unread-dot", "notification-count", "red-dot", "data-count"):
            assert marker not in text, f"a {marker} is a number pointed at a parent"


class TestRestraintIsMeasurable:
    def test_the_touch_target_holds_for_every_hand(self):
        assert tokens()["layout"]["touch"] >= 44

    def test_motion_has_a_ceiling_with_one_documented_exception(self):
        durations = tokens()["duration"]
        over = {k: v for k, v in durations.items() if v > durations["considered"]}
        assert set(over) == {"flip"}, f"motion budget exceeded by {over}"

    def test_space_is_a_scale(self):
        for name, value in tokens()["space"].items():
            assert value % 4 == 0 or value == 2, f"space.{name} = {value} is off the scale"


class TestTheEmittedStylesheetSurvivesEveryViewer:
    """The classic unreadable-page bug, as a test.

    A viewer is in one of three states: explicit light, explicit dark, or the default
    system setting, which stamps nothing at all on the root element.
    """

    def test_the_bare_root_carries_the_whole_light_palette(self):
        css = world_css()
        before_any_guard = css[: css.index("@media")]
        missing = [t["name"] for t in colors() if f"--w-color-{t['name']}" not in before_any_guard]
        assert not missing, (
            f"defined only behind a guard, so a system-default viewer never gets them: {missing}"
        )

    def test_dark_is_reachable_by_preference_and_by_choice(self):
        css = world_css()
        assert ':root:not([data-theme="light"])' in css, (
            "an explicit light choice must beat a dark OS"
        )
        assert ':root[data-theme="dark"]' in css, "the toggle must win in the other direction"

    def test_the_ground_is_painted_rather_than_borrowed(self):
        assert re.search(r"body \{[^}]*background: var\(--w-color-ground\)", world_css())

    def test_reduced_motion_is_honoured_for_every_duration(self):
        reduced = world_css()[world_css().index("prefers-reduced-motion") :]
        for name in tokens()["duration"]:
            assert f"--w-duration-{name}: 1ms;" in reduced, name

    def test_the_emitted_css_is_not_stale(self):
        """tokens() raises if src/ is newer than dist/; this makes that explicit."""
        assert (DIST / "tokens.json").exists()
        tokens()
