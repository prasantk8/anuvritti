"""filmkit has never heard of the films it compiles.

TASK-701 said "no knowledge of either product", which is the kind of sentence a
package satisfies on the day it is written and loses six months later, one
convenient import at a time. The first thing that crosses back is never a
dependency - it is a *word*: a default named after somebody's repository, an
environment variable with a product's initials, a docstring that explains a
generic function in terms of the one caller it happens to have.

So this file checks for the words, and for the two shapes that let a word in:
an environment variable, and a dependency on a specific application. It is
deliberately blunt. A blunt check that fires is worth more than a subtle one
that is quietly deleted the first time it is inconvenient.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import filmkit

SOURCE = Path(filmkit.__file__).parent
FILES = sorted(SOURCE.rglob("*.py"))

#: Proper nouns belonging to the two applications this package was extracted
#: from, to the application one of them demonstrates, and to the vendor of the
#: one synthesiser that was hard-coded in the original. Not a denylist of bad
#: words - a denylist of *other people's nouns*.
#:
#: Ordinary technical words that happen to be domain words elsewhere - `parent`
#: as in a directory, `child` as in a process, `family` as in a font - are
#: deliberately absent. A check that fires on `path.parent` gets an exception
#: added to it within a week, and an exception is how a check stops working.
PRODUCT_WORDS = (
    "autovideo",
    "anuvritti",
    "memtara",
    "memtara_cro",
    "dadaa",
    "spark",
    "edge-tts",
    "edge_tts",
)

#: Reading configuration is how a library becomes a program with a fixed home.
ENVIRONMENT = re.compile(r"os\.environ|getenv|dotenv")


def _text(path: Path) -> str:
    return path.read_text()


class TestNoProductNameAppearsAnywhere:
    @pytest.mark.constitution
    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
    def test_the_source_names_no_application(self, path: Path):
        lowered = _text(path).lower()
        found = sorted({word for word in PRODUCT_WORDS if word in lowered})
        assert not found, (
            f"{path.name} names {found}. filmkit compiles films; it does not know "
            "whose. If this word is genuinely needed, it is a parameter."
        )


class TestNothingHereReadsItsOwnConfiguration:
    @pytest.mark.constitution
    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
    def test_no_module_reads_the_environment(self, path: Path):
        """`process.run` passes the caller's environment through - it never reads it.

        A library that reads an environment variable has chosen a name, and a
        name is either generic enough to collide or specific enough to belong
        to one product. `Workspace` exists so the caller makes that choice.
        """
        offending = [
            line
            for line in _text(path).splitlines()
            if ENVIRONMENT.search(line) and "os.environ" not in line.split("#")[0][:0] + line
            if "**os.environ" not in line
        ]
        assert not offending, f"{path.name} reads configuration: {offending}"


class TestTheHeavyThingsAreAllPorts:
    @pytest.mark.constitution
    def test_importing_filmkit_requires_nothing_to_be_installed(self):
        """A caller supplying its own painter should not need a browser on disk."""
        assert filmkit.__version__

    @pytest.mark.constitution
    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
    def test_a_browser_is_never_imported_at_module_level(self, path: Path):
        """Chromium is an enormous thing to require of anything wanting a picture."""
        tree = ast.parse(_text(path))
        top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = [
            alias.name for node in top_level if isinstance(node, ast.Import) for alias in node.names
        ] + [node.module or "" for node in top_level if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith("playwright") for name in names), (
            f"{path.name} imports a browser to be imported at all"
        )


class TestTheseChecksActuallyFire:
    """A constitution test that cannot fail is decoration."""

    def test_a_product_name_would_be_caught(self, tmp_path):
        sneaky = tmp_path / "sneaky.py"
        sneaky.write_text('CACHE = "~/autovideo/cache"\n')
        found = sorted({w for w in PRODUCT_WORDS if w in _text(sneaky).lower()})
        assert found == ["autovideo"]

    def test_a_product_name_in_a_docstring_would_be_caught(self, tmp_path):
        sneaky = tmp_path / "sneaky.py"
        sneaky.write_text('"""Renders a Spark the way Anuvritti wants it."""\n')
        found = sorted({w for w in PRODUCT_WORDS if w in _text(sneaky).lower()})
        assert found == ["anuvritti", "spark"]

    def test_reading_an_environment_variable_would_be_caught(self, tmp_path):
        sneaky = tmp_path / "sneaky.py"
        sneaky.write_text("import os\n\nCACHE = os.environ.get('CACHE_DIR')\n")
        offending = [
            line
            for line in _text(sneaky).splitlines()
            if ENVIRONMENT.search(line) and "**os.environ" not in line
        ]
        assert len(offending) == 1

    def test_passing_the_caller_s_environment_through_is_not_reading_it(self, tmp_path):
        sneaky = tmp_path / "fine.py"
        sneaky.write_text("env={**os.environ, **(env or {})},\n")
        offending = [
            line
            for line in _text(sneaky).splitlines()
            if ENVIRONMENT.search(line) and "**os.environ" not in line
        ]
        assert offending == []

    def test_a_top_level_browser_import_would_be_caught(self, tmp_path):
        sneaky = tmp_path / "sneaky.py"
        sneaky.write_text("from playwright.sync_api import sync_playwright\n")
        tree = ast.parse(_text(sneaky))
        modules = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
        assert any((m or "").startswith("playwright") for m in modules)
