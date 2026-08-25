"""Generate the typed client from docs/contracts/openapi.yaml (TASK-505).

Why a bespoke generator rather than `openapi-typescript` or `@hey-api/openapi-ts`, both of
which are good and would work:

* **The output must be zero-dependency, and so must the tool.** `packages/world` already
  proved the shape: Node strips the types natively and `node:test` runs the suite, with no
  `node_modules` anywhere. Adding a generator would put a `node_modules` and a lockfile back
  into the one place this repository has managed without them. (It would also mean pinning
  `typescript@5.9` in a codegen workspace, since `openapi-typescript@7.13` builds output via
  the `ts.factory` compiler API that TypeScript 7 does not expose.)
* **The spec is small, hand-written and ours.** A generator that understands exactly the
  subset we use, and *refuses* everything else, is a few hundred readable lines. The refusal
  is the point: an unsupported construct is a loud failure rather than a silent `unknown`.
* **The emitted shapes are load-bearing.** `Instant` and `Elapsed` are branded so the
  interface cannot do date arithmetic (TASK-507); a general-purpose generator emits `string`.

The emitted file is committed, and `tests/design` fails if it drifts. Generated code that is
not checked is a second source of truth wearing the first one's clothes.

Erasable syntax only: Node's type stripping rejects `enum`, `namespace`, parameter
properties, decorators, `import x = require`, `export =`, and `using` declarations. String
unions plus `as const` objects give everything an enum would, with nothing to strip.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "contracts" / "openapi.yaml"
OUT = ROOT / "packages" / "client" / "src" / "generated" / "contract.ts"

#: Operational endpoints. A load balancer is not a client of the family's API.
SKIP_PATHS = {"/health", "/ready", "/metrics"}

#: Brands the generator knows. An unknown one is an error, not a `string`, so a typo in the
#: contract cannot quietly remove the protection the brand exists to provide.
BRANDS = {"Instant", "Elapsed"}

HEADER = """// Generated from docs/contracts/openapi.yaml by packages/client/codegen/generate.py.
// Do not edit. Run `make client` and commit the result; `make design` fails on drift.
//
// Erasable syntax only - Node strips these types rather than compiling them, so there are
// no enums, no namespaces and nothing else that would need a build step.
"""


class UnsupportedError(Exception):
    """A construct this generator will not guess at.

    Raised rather than emitting `unknown`, because a client that silently types a field as
    `unknown` is how a contract stops being enforced without anyone noticing.
    """


# --------------------------------------------------------------------------- naming
def _pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.replace("-", "_").split("_"))


def _camel(name: str) -> str:
    head, *rest = name.replace("-", "_").split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _ref_name(ref: str) -> str:
    if not ref.startswith("#/components/schemas/"):
        raise UnsupportedError(f"only local schema refs are supported, got {ref!r}")
    return _pascal(ref.rsplit("/", 1)[-1])


# ---------------------------------------------------------------------------- types
def _type_of(schema: Any, *, spec: dict[str, Any], context: str, depth: int = 0) -> str:
    """One JSON Schema node to one TypeScript type."""
    if schema is None or schema == {}:
        return "unknown"
    if "$ref" in schema:
        return _ref_name(schema["$ref"])

    brand = schema.get("x-anuvritti-brand")
    if brand is not None:
        if brand not in BRANDS:
            raise UnsupportedError(f"{context}: unknown brand {brand!r}; known brands are {BRANDS}")
        return brand

    if "allOf" in schema:
        parts = (_type_of(p, spec=spec, context=context, depth=depth) for p in schema["allOf"])
        return " & ".join(parts)
    if "oneOf" in schema or "anyOf" in schema:
        members = schema.get("oneOf") or schema["anyOf"]
        return " | ".join(
            _type_of(part, spec=spec, context=context, depth=depth) for part in members
        )

    kind = schema.get("type")
    if isinstance(kind, list):
        raise UnsupportedError(f"{context}: union `type` lists are not supported")

    if "enum" in schema:
        return " | ".join(f'"{value}"' for value in schema["enum"])

    if kind == "string":
        base = "Instant" if schema.get("format") == "date-time" else "string"
        return f"{base} | null" if schema.get("nullable") else base
    if kind in {"integer", "number"}:
        return "number | null" if schema.get("nullable") else "number"
    if kind == "boolean":
        return "boolean"
    if kind == "array":
        inner = _type_of(schema.get("items"), spec=spec, context=context, depth=depth)
        return f"readonly {_wrap(inner)}[]"
    if kind == "object" or "properties" in schema:
        return _object_type(schema, spec=spec, context=context, depth=depth)
    if kind is None:
        return "unknown"
    raise UnsupportedError(f"{context}: unsupported schema type {kind!r}")


def _wrap(inner: str) -> str:
    """Parenthesise a union before `[]`, so `A | B` becomes `(A | B)[]` and not `A | B[]`."""
    return f"({inner})" if any(token in inner for token in (" | ", " & ")) else inner


def _object_type(
    schema: dict[str, Any], *, spec: dict[str, Any], context: str, depth: int = 0
) -> str:
    properties = schema.get("properties") or {}
    if not properties:
        return "Record<string, unknown>"
    required = set(schema.get("required") or [])
    pad = "  " * (depth + 1)
    fields = []
    for name, member in properties.items():
        optional = "" if name in required else "?"
        rendered = _type_of(member, spec=spec, context=f"{context}.{name}", depth=depth + 1)
        if member.get("nullable") and "null" not in rendered:
            rendered = f"{rendered} | null"
        fields.append(f"{pad}readonly {name}{optional}: {rendered};")
    return "{\n" + "\n".join(fields) + "\n" + "  " * depth + "}"


def _doc(schema: dict[str, Any], indent: str = "") -> str:
    text = (schema.get("description") or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) == 1:
        return f"{indent}/** {lines[0]} */\n"
    body = "\n".join(f"{indent} * {line}" for line in lines)
    return f"{indent}/**\n{body}\n{indent} */\n"


def _emit_schemas(spec: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for raw_name, schema in spec["components"]["schemas"].items():
        name = _pascal(raw_name)
        context = f"schemas.{raw_name}"
        out.append(_doc(schema))
        if "enum" in schema:
            values = schema["enum"]
            union = " | ".join(f'"{value}"' for value in values)
            listed = ", ".join(f'"{value}"' for value in values)
            # `as const` object rather than `enum`: same call sites, nothing to strip.
            out.append(f"export type {name} = {union};\n")
            out.append(
                f"export const {_screaming(raw_name)}: readonly {name}[] = [{listed}] as const;\n"
            )
            continue
        body = _type_of(schema, spec=spec, context=context)
        keyword = "interface" if body.startswith("{") else "type"
        joiner = " " if keyword == "interface" else " = "
        terminator = "" if keyword == "interface" else ";"
        out.append(f"export {keyword} {name}{joiner}{body}{terminator}\n")
    return out


def _screaming(name: str) -> str:
    spaced = "".join(f"_{c}" if c.isupper() else c for c in name).lstrip("_")
    return spaced.upper().replace("__", "_") + "_VALUES"


# ----------------------------------------------------------------------- operations
def _body_type(operation: dict[str, Any], spec: dict[str, Any]) -> str | None:
    body = operation.get("requestBody")
    if not body:
        return None
    content = body.get("content") or {}
    if "application/json" in content:
        return _type_of(content["application/json"]["schema"], spec=spec, context="body")
    if "multipart/form-data" in content:
        return "FormData"
    raise UnsupportedError(f"unsupported request media types: {sorted(content)}")


def _response_type(operation: dict[str, Any], spec: dict[str, Any]) -> str:
    for status in ("200", "201"):
        response = (operation.get("responses") or {}).get(status)
        if not response:
            continue
        content = response.get("content") or {}
        if "application/json" in content:
            return _type_of(content["application/json"]["schema"], spec=spec, context="response")
        if content:
            return "Uint8Array"
        return "void"
    return "void"


def _parameters(operation: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    resolved = []
    for parameter in operation.get("parameters") or []:
        if "$ref" in parameter:
            key = parameter["$ref"].rsplit("/", 1)[-1]
            parameter = spec["components"]["parameters"][key]
        resolved.append(parameter)
    return resolved


def _emit_operations(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (descriptor lines, interface method lines)."""
    descriptors: list[str] = []
    methods: list[str] = []

    for path, operations in spec["paths"].items():
        if path in SKIP_PATHS:
            continue
        for verb, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            name = operation.get("operationId")
            if not name:
                raise UnsupportedError(f"{verb.upper()} {path} has no operationId")

            parameters = _parameters(operation, spec)
            path_params = [p for p in parameters if p.get("in") == "path"]
            query_params = [p for p in parameters if p.get("in") == "query"]
            takes_key = any(p.get("name") == "Idempotency-Key" for p in parameters)
            body_type = _body_type(operation, spec)
            returns = _response_type(operation, spec)
            open_route = operation.get("security") == []

            arguments: list[str] = []
            for parameter in path_params:
                arguments.append(f"{_camel(parameter['name'])}: string")
            if body_type:
                arguments.append(f"body: {body_type}")
            if query_params:
                fields = " ".join(
                    f"readonly {_camel(p['name'])}?: "
                    f"{_type_of(p.get('schema') or {}, spec=spec, context=p['name'])};"
                    for p in query_params
                )
                arguments.append(f"query?: {{ {fields} }}")
            arguments.append("options?: RequestOptions" if takes_key else "options?: CallOptions")

            methods.append(_doc(operation, indent="  "))
            methods.append(f"  {name}({', '.join(arguments)}): Promise<Result<{returns}>>;\n")

            descriptors.append(
                f'  {name}: {{ method: "{verb.upper()}", path: "{path}", '
                f"pathParams: [{', '.join(chr(34) + p['name'] + chr(34) for p in path_params)}], "
                f"queryParams: [{', '.join(chr(34) + p['name'] + chr(34) for p in query_params)}], "
                f"hasBody: {str(bool(body_type)).lower()}, "
                f"idempotent: {str(takes_key).lower()}, "
                f"open: {str(open_route).lower()} }},\n"
            )
    return descriptors, methods


# ---------------------------------------------------------------------------- emit
def generate(spec: dict[str, Any]) -> str:
    descriptors, methods = _emit_operations(spec)
    parts = [
        HEADER,
        '\nimport type { CallOptions, RequestOptions, Result } from "../runtime/types.ts";\n',
        "\nexport type { CallOptions, RequestOptions, Result };\n",
        "\n/**\n"
        " * An instant in time, as the server wrote it.\n"
        " *\n"
        " * Branded, and deliberately not a `Date`. TASK-507 says the interface never renders\n"
        " * elapsed time as a number, and the cheapest way for that to fail is for someone to\n"
        " * reach for `Date.now() - new Date(created_at)` under a deadline. This type does not\n"
        " * subtract. Use `saved` or `elapsed`, which arrive already worded.\n"
        " */\n"
        "export type Instant = string & { readonly __instant: unique symbol };\n",
        "\n/**\n"
        " * How long ago something was, in the words a parent would use.\n"
        " *\n"
        ' * "8 months ago", never "247". Branded so it cannot be confused with an arbitrary\n'
        " * string, and so a search for what produces one finds every site at once.\n"
        " */\n"
        "export type Elapsed = string & { readonly __elapsed: unique symbol };\n",
        f'\nexport const API_VERSION = "{spec["info"]["version"]}";\n',
        "\n// ---------------------------------------------------------------- schemas\n",
        *_emit_schemas(spec),
        "\n// ------------------------------------------------------------- operations\n",
        "\n/** What each operation is, so the transport is written once rather than per call. */\n",
        "export const OPERATIONS = {\n",
        *descriptors,
        "} as const;\n",
        "\nexport type OperationName = keyof typeof OPERATIONS;\n",
        "\n/** The generated surface. One method per documented operation, and no others. */\n",
        "export interface Contract {\n",
        *methods,
        "}\n",
    ]
    return "".join(parts)


def main() -> int:
    spec = yaml.safe_load(CONTRACT.read_text())
    try:
        emitted = generate(spec)
    except UnsupportedError as exc:
        print(f"contract uses something the generator will not guess at:\n  {exc}", file=sys.stderr)
        return 1

    check = "--check" in sys.argv
    existing = OUT.read_text() if OUT.exists() else None
    if check:
        if existing != emitted:
            print(
                f"{OUT.relative_to(ROOT)} is stale. Run `make client` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"client is generated from the current contract - {len(emitted.splitlines())} lines")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(emitted)
    print(f"wrote {OUT.relative_to(ROOT)} - {len(emitted.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
