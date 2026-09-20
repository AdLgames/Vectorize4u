"""Generate `types.ts` from the FastAPI OpenAPI schema (§11).

Generated, never hand-written. A hand-maintained copy of an API contract
drifts silently, and the first symptom is a runtime error in a paying
customer's browser — so the file this writes is checked in, and a test
regenerates it and fails if the checked-in copy is stale.

    python packages/shared/generate.py            # write types.ts
    python packages/shared/generate.py --check    # fail if it would change
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "types.ts"

HEADER = """// Generated from the FastAPI OpenAPI schema. Do not edit by hand.
// Run `make types` (or `python packages/shared/generate.py`) after changing
// anything in apps/api/app/schemas.py.

"""

# FastAPI's generated names for multipart bodies are unreadable, and nothing
# outside the API has a use for the validation-error envelope.
SKIP_PREFIXES = ("Body_", "HTTPValidationError", "ValidationError")


def ts_type(node: dict[str, Any]) -> str:
    if "$ref" in node:
        return node["$ref"].rsplit("/", 1)[-1]

    if "anyOf" in node:
        parts = [ts_type(option) for option in node["anyOf"]]
        # `X | null` reads better than `null | X`, and dedupe: Optional[str]
        # with a constraint can produce the same branch twice.
        ordered = [p for p in dict.fromkeys(parts) if p != "null"]
        if len(parts) != len(ordered):
            ordered.append("null")
        return " | ".join(ordered)

    if "const" in node:
        return f'"{node["const"]}"'

    kind = node.get("type")
    if kind == "array":
        inner = ts_type(node.get("items", {}))
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if kind == "object":
        extra = node.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Record<string, {ts_type(extra)}>"
        return "Record<string, unknown>"
    if kind == "string":
        if node.get("enum"):
            return " | ".join(f'"{value}"' for value in node["enum"])
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    return "unknown"


def referenced(node: Any, schemas: dict[str, Any], seen: set[str]) -> None:
    """Collect every schema name reachable from `node`."""
    if isinstance(node, list):
        for item in node:
            referenced(item, schemas, seen)
        return
    if not isinstance(node, dict):
        return
    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name not in seen:
            seen.add(name)
            referenced(schemas.get(name, {}), schemas, seen)
    for value in node.values():
        referenced(value, schemas, seen)


def request_schemas(spec: dict[str, Any]) -> set[str]:
    """Names reachable from a request body, transitively.

    The distinction matters: a field with a default is optional to *send*
    and always present in what comes *back*. Marking a response field
    optional makes every caller check for an absence the server never sends.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    seen: set[str] = set()
    for operations in spec.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict) and "requestBody" in operation:
                referenced(operation["requestBody"], schemas, seen)
    return seen


def render(name: str, schema: dict[str, Any], *, sent_by_the_client: bool) -> str:
    required = set(schema.get("required", []))
    lines = [f"export type {name} = {{"]
    for field, node in schema.get("properties", {}).items():
        # A response model serialises every field it has, so only request
        # types get `?`. Absence in a response is spelled `| null`, and a
        # caller should not have to check for both.
        optional = "?" if sent_by_the_client and field not in required else ""
        description = node.get("description")
        if description:
            lines.append(f"  /** {description} */")
        lines.append(f"  {field}{optional}: {ts_type(node)};")
    lines.append("};")
    return "\n".join(lines)


def generate() -> str:
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    import os

    os.environ.setdefault("VEC_ENVIRONMENT", "test")
    from app.main import app  # imported here: sys.path is set up just above

    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    sent = request_schemas(spec)
    blocks = [
        render(name, schema, sent_by_the_client=name in sent)
        for name, schema in sorted(schemas.items())
        if not name.startswith(SKIP_PREFIXES)
    ]
    return HEADER + "\n\n".join(blocks) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    content = generate()
    if args.check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != content:
            print(f"{OUTPUT} is stale — run `make types`", file=sys.stderr)
            return 1
        return 0

    OUTPUT.write_text(content)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
