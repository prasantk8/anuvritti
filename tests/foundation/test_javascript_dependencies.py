"""The app, client and visual world install as one reproducible workspace."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_one_root_lock_owns_every_javascript_package() -> None:
    workspace = json.loads((ROOT / "package.json").read_text())
    lock = json.loads((ROOT / "package-lock.json").read_text())

    assert workspace["workspaces"] == ["apps/*", "packages/*"]
    assert "apps/anuvritti" in lock["packages"]
    assert "packages/client" in lock["packages"]
    assert "packages/world" in lock["packages"]
    assert not (ROOT / "apps/anuvritti/package-lock.json").exists()


def test_app_direct_dependencies_are_exactly_pinned() -> None:
    package = json.loads((ROOT / "apps/anuvritti/package.json").read_text())

    for group in ("dependencies", "devDependencies"):
        drifting = {
            name: version
            for name, version in package[group].items()
            if not version.startswith("file:") and version[:1] in {"^", "~", ">", "*"}
        }
        assert drifting == {}


def test_offline_renderer_resolves_fonts_through_the_workspace() -> None:
    source = (ROOT / "packages/world/scripts/render-film.ts").read_text()

    assert "createRequire(import.meta.url)" in source
    assert 'join(root, "node_modules"' not in source
