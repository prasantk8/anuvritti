"""TASK-603 - a family's audio has nowhere to go (PRD 39, 44).

PRD 44 lists "no public-model training by default" among the core privacy principles, and
the load-bearing word is *default*. A default is a setting: a future release, a hurried
deployment or a well-meaning environment variable can flip it, and nothing in the test
suite would notice. This file makes it structural instead.

The check is a **static walk of the import graph**, not a runtime assertion, and the
difference matters. A runtime check fires on the request that has already sent the audio -
by then a child's voice is in someone else's log. A static check fires in CI, on the commit
that added the import, before anything has been sent anywhere.

It is deliberately scoped to `anuvritti.adapters`. The HTTP interface obviously speaks over
a socket; that is its job, and the family chose to run it. What must never happen is a
*background* path - a transcription, an enrichment, a "just check if there is an update" -
that reaches the network from inside the part of the system that holds the bytes.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

import pytest

import anuvritti

SOURCE_ROOT = Path(anuvritti.__file__).parent
ADAPTERS = SOURCE_ROOT / "adapters"

#: Every module in the standard library or the ecosystem that can open a connection, plus
#: the vendor SDKs whose entire purpose is to send text somewhere and get text back.
#:
#: `urllib.parse` is deliberately absent and `urllib.request` is deliberately present:
#: parsing a URL is string handling, and `domain/values.py` does it to decide whether a
#: Spark's source is well-formed. Fetching one is the thing this file exists to forbid.
FORBIDDEN: frozenset[str] = frozenset(
    {
        "socket",
        "socketserver",
        "ssl",
        "asyncio",
        "selectors",
        "http",
        "http.client",
        "urllib.request",
        "urllib.error",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "xmlrpc",
        "webbrowser",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
        "websockets",
        "grpc",
        "boto3",
        "botocore",
        "openai",
        "anthropic",
        "google",
        "cohere",
        "replicate",
        "huggingface_hub",
        "transformers",
    }
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports_of(path: Path) -> set[str]:
    """Every module this file imports, however it phrases it.

    `from x import y` counts as importing `x` *and* `x.y`, because `from urllib import
    request` is exactly the phrasing someone reaches for when a linter complained about
    the obvious one.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _offending(imported: str) -> str | None:
    """`http.client` offends, and so does `http`. `httpx_stub` does not."""
    parts = imported.split(".")
    for depth in range(1, len(parts) + 1):
        prefix = ".".join(parts[:depth])
        if prefix in FORBIDDEN:
            return prefix
    return None


def _reachable_from(start: Path) -> dict[str, Path]:
    """Every module in *this project* transitively imported by `start`.

    Third-party imports are checked but not walked into: whether `pydantic` imports a
    socket is not this project's business, and following it would turn a fast structural
    check into a whole-ecosystem audit that nobody would keep running.
    """
    by_name = {_module_name(p): p for p in SOURCE_ROOT.rglob("*.py")}
    seen: dict[str, Path] = {_module_name(start): start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for imported in _imports_of(current):
            path = by_name.get(imported)
            if path is not None and _module_name(path) not in seen:
                seen[_module_name(path)] = path
                queue.append(path)
    return seen


ADAPTER_FILES = sorted(ADAPTERS.rglob("*.py"))


class TestNothingUnderAdaptersCanReachTheNetwork:
    @pytest.mark.parametrize("path", ADAPTER_FILES, ids=lambda p: p.stem)
    def test_no_adapter_imports_a_way_out(self, path: Path):
        offenders = {
            imported: offence for imported in _imports_of(path) if (offence := _offending(imported))
        }
        assert not offenders, (
            f"{_module_name(path)} can reach the network: {sorted(offenders)}. "
            "If this is deliberate, it is a decision about a family's private audio and "
            "belongs in a document, not in an import."
        )

    def test_the_transcriber_is_clean_all_the_way_down(self):
        """The one that actually holds the bytes, checked transitively.

        `test_no_adapter_imports_a_way_out` is per-file. This walks the whole closure, so a
        transcriber that imports a helper that imports `httpx` is caught too.
        """
        closure = _reachable_from(ADAPTERS / "transcription" / "local.py")
        offenders: dict[str, list[str]] = {}
        for name, path in closure.items():
            found = sorted(o for i in _imports_of(path) if (o := _offending(i)))
            if found:
                offenders[name] = found
        assert not offenders, f"the transcription path can reach the network: {offenders}"

    def test_the_closure_is_not_trivially_small(self):
        """Proving the walk above is actually walking.

        A `_reachable_from` that quietly returned only its starting module would pass every
        assertion in this file forever while checking nothing.
        """
        closure = _reachable_from(ADAPTERS / "transcription" / "local.py")
        assert len(closure) > 5
        assert "anuvritti.domain.voice" in closure
        assert "anuvritti.application.ports" in closure


class TestTheCheckItselfWorks:
    """A constitution test that cannot fail is decoration. These make it fail."""

    @pytest.mark.parametrize(
        "imported,expected",
        [
            ("socket", "socket"),
            ("http.client", "http"),
            ("urllib.request", "urllib.request"),
            ("openai", "openai"),
            ("httpx", "httpx"),
        ],
    )
    def test_it_recognises_a_way_out(self, imported, expected):
        assert _offending(imported) == expected

    @pytest.mark.parametrize(
        "imported", ["urllib.parse", "hashlib", "sqlite3", "httpx_is_not_httpx", "anuvritti.domain"]
    )
    def test_it_does_not_cry_wolf(self, imported):
        assert _offending(imported) is None

    def test_it_catches_the_phrasing_someone_would_reach_for(self, tmp_path: Path):
        """`from urllib import request` is what gets written after a linter complains."""
        sneaky = tmp_path / "sneaky.py"
        sneaky.write_text("from urllib import request\n\n\ndef send(x):\n    return request\n")
        offences = {o for i in _imports_of(sneaky) if (o := _offending(i))}
        assert offences == {"urllib.request"}
