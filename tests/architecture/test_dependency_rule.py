"""TASK-104 - the dependency rule as an executable fitness function (ADR-0001).

Clean Architecture only holds if something checks it. A code review will not catch the
import that quietly makes the domain depend on SQLite; this test will.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "anuvritti"

#: layer -> layers it is allowed to import from (plus itself).
#: `shared` and `config` are cross-cutting: vocabulary and 12-factor settings. The domain
#: is allowed neither piece of infrastructure beyond `shared`, which has no dependencies.
ALLOWED: dict[str, frozenset[str]] = {
    "shared": frozenset(),
    "domain": frozenset({"shared"}),
    "application": frozenset({"shared", "domain"}),
    "adapters": frozenset({"shared", "domain", "application", "config"}),
    "interfaces": frozenset({"shared", "domain", "application", "adapters", "config"}),
    "config": frozenset({"shared"}),
    "observability": frozenset({"shared", "domain"}),
    "infrastructure": frozenset({"shared", "domain", "config"}),
}

#: third-party distributions the domain may never touch
FORBIDDEN_IN_DOMAIN = {"fastapi", "starlette", "pydantic", "sqlite3", "uvicorn", "cryptography"}

STDLIB = frozenset(sys.stdlib_module_names)


def _modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.name != "__init__.py")


def _layer_of(path: Path) -> str:
    return path.relative_to(SRC).parts[0]


def _imports(path: Path) -> set[str]:
    """Top-level module name of every import in the file."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def _anuvritti_layers_imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    layers: set[str] = set()
    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("anuvritti."):
                    layers.add(alias.name.split(".")[1])
            continue
        if module and module.startswith("anuvritti."):
            parts = module.split(".")
            if len(parts) > 1:
                layers.add(parts[1])
    return layers


def test_source_tree_is_not_empty():
    assert _modules(), "fitness function would vacuously pass on an empty tree"


@pytest.mark.parametrize("module", _modules(), ids=lambda p: str(p.relative_to(SRC)))
def test_layer_only_imports_layers_it_is_allowed_to(module: Path):
    layer = _layer_of(module)
    permitted = ALLOWED[layer] | {layer}
    violations = _anuvritti_layers_imported(module) - permitted
    assert not violations, (
        f"{module.relative_to(SRC)} is in `{layer}` and imports {sorted(violations)}. "
        f"The dependency rule (ADR-0001) allows only {sorted(permitted)}."
    )


@pytest.mark.parametrize(
    "module",
    [m for m in _modules() if _layer_of(m) == "domain"],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_domain_imports_stdlib_only(module: Path):
    """The domain must be portable, offline and free of infrastructure (ADR-0001)."""
    external = {
        name
        for name in _imports(module)
        if name not in STDLIB and name != "anuvritti" and not name.startswith("_")
    }
    assert not external, f"{module.relative_to(SRC)} imports non-stdlib {sorted(external)}"


@pytest.mark.parametrize(
    "module",
    [m for m in _modules() if _layer_of(m) == "domain"],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_domain_never_touches_infrastructure_libraries(module: Path):
    assert not (_imports(module) & FORBIDDEN_IN_DOMAIN)


def test_application_defines_ports_but_imports_no_adapter():
    """Dependency inversion: the application declares what it needs, adapters supply it."""
    for module in _modules():
        if _layer_of(module) == "application":
            assert "adapters" not in _anuvritti_layers_imported(module), module
