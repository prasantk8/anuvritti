"""TASK-505 - the generated client is not allowed to drift from the contract.

`packages/client/src/generated/contract.ts` is committed, because a client that has to be
built before it can be read is a client nobody reads. The cost of committing generated code
is that it can silently stop matching what generated it, so this is the thing that notices.

It also runs the generator, which means the generator's own refusal to guess is exercised on
every gate: a contract that grew a construct the generator does not understand fails here
rather than emitting `unknown` and letting the app compile against a lie.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "packages" / "client" / "codegen" / "generate.py"
GENERATED = ROOT / "packages" / "client" / "src" / "generated" / "contract.ts"
CONTRACT = ROOT / "docs" / "contracts" / "openapi.yaml"


def _generator():
    spec = importlib.util.spec_from_file_location("anuvritti_client_codegen", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def codegen():
    return _generator()


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(CONTRACT.read_text())


class TestTheClientMatchesTheContract:
    def test_the_committed_file_is_what_the_generator_produces(self, codegen, spec):
        assert GENERATED.exists(), "run `make client`"
        assert GENERATED.read_text() == codegen.generate(spec), (
            "packages/client/src/generated/contract.ts is stale. Run `make client`."
        )

    def test_generating_twice_gives_the_same_bytes(self, codegen, spec):
        """Otherwise the drift check above would fail at random and get turned off."""
        assert codegen.generate(spec) == codegen.generate(spec)

    def test_the_generator_refuses_rather_than_guesses(self, codegen):
        """The property that makes a bespoke generator safe.

        A construct it does not understand must stop the build. Emitting `unknown` would
        let the app typecheck against a field the server never sends.
        """
        broken = {
            "info": {"version": "0.0.0"},
            "paths": {},
            "components": {
                "schemas": {"Thing": {"type": "object", "properties": {"x": {"type": "geography"}}}}
            },
        }
        with pytest.raises(codegen.UnsupportedError, match="geography"):
            codegen.generate(broken)

    def test_an_unknown_brand_is_an_error_not_a_plain_string(self, codegen):
        """A typo in `x-anuvritti-brand` must not silently remove the protection."""
        broken = {
            "info": {"version": "0.0.0"},
            "paths": {},
            "components": {
                "schemas": {
                    "Thing": {
                        "type": "object",
                        "properties": {"when": {"type": "string", "x-anuvritti-brand": "Instnat"}},
                    }
                }
            },
        }
        with pytest.raises(codegen.UnsupportedError, match="Instnat"):
            codegen.generate(broken)

    def test_an_operation_without_a_name_is_an_error(self, codegen):
        """Otherwise it is skipped, and the endpoint exists in the server and not in the app."""
        broken = {
            "info": {"version": "0.0.0"},
            "paths": {"/thing": {"get": {"summary": "no id"}}},
            "components": {"schemas": {}},
        }
        with pytest.raises(codegen.UnsupportedError, match="operationId"):
            codegen.generate(broken)


class TestTheGeneratedCodeStaysErasable:
    """Node strips these types rather than compiling them, so a build step is not optional -
    it is impossible. Anything non-erasable would fail to load at runtime."""

    @pytest.mark.parametrize(
        "construct",
        ["enum ", "namespace ", "declare module", "abstract class", "using ", "export ="],
    )
    def test_no_construct_that_would_need_a_compiler(self, construct: str):
        assert construct not in GENERATED.read_text(), (
            f"`{construct.strip()}` is not erasable syntax; the client would need a build step"
        )

    def test_the_branded_types_survived_generation(self):
        """TASK-507's client half. If these become `string`, date arithmetic compiles again."""
        emitted = GENERATED.read_text()
        assert "export type Instant = string & { readonly __instant: unique symbol };" in emitted
        assert "export type Elapsed = string & { readonly __elapsed: unique symbol };" in emitted
        assert "readonly saved: Elapsed;" in emitted
        assert "readonly elapsed: Elapsed;" in emitted
