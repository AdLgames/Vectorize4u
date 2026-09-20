"""The public API docs (§9) against the live schema.

Docs that lie are worse than no docs, and API docs lie by default: the
code moves and the page does not. So the page's reference content is data
(`apps/web/lib/apiReference.ts`) and this test is what keeps it honest.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "apiReference.ts"

# Endpoints the public docs deliberately leave out: Stripe's callback, the
# browser's own checkout and plan routes, the local-storage shims, and the
# dev-only sign-in. If you add a *public* endpoint it must be documented,
# which is the point of the second test below.
UNDOCUMENTED = {
    "/health",
    "/v1/plans",
    "/v1/checkout",
    "/v1/billing/portal",
    "/v1/stripe/webhook",
    "/v1/files/upload",
    "/v1/files/download",
    "/v1/dev/session",
}


@pytest.fixture(scope="module")
def reference() -> str:
    if not REFERENCE.exists():  # pragma: no cover - the web app is a sibling
        pytest.skip("the web app is not checked out next to the API")
    return REFERENCE.read_text()


@pytest.fixture(scope="module")
def schema():
    from app.main import app

    return app.openapi()


def documented_endpoints(reference: str) -> set[tuple[str, str]]:
    return {
        (method.lower(), path)
        for method, path in re.findall(
            r'method:\s*"(GET|POST|PUT|DELETE)",\s*path:\s*"([^"]+)"', reference
        )
    }


def test_the_docs_list_at_least_one_of_everything(reference):
    """A regex that silently matches nothing would make every other
    assertion here vacuous."""
    assert len(documented_endpoints(reference)) > 10
    assert "v4u_live_" in reference


def test_every_documented_endpoint_exists(reference, schema):
    live = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
    }
    missing = documented_endpoints(reference) - live
    assert not missing, f"documented but not served: {sorted(missing)}"


def test_every_public_endpoint_is_documented(reference, schema):
    documented = documented_endpoints(reference)
    undocumented = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
        if path not in UNDOCUMENTED and (method, path) not in documented
    }
    assert not undocumented, f"served but not documented: {sorted(undocumented)}"


def test_every_documented_option_is_a_real_option(reference):
    from app.schemas import JobOptions

    documented = set()
    for name in re.findall(r'name:\s*"([^"]+)"', reference):
        documented.update(part.strip() for part in name.split("/"))

    real = set(JobOptions.model_fields)
    # The error-code table uses `code:`, not `name:`, so nothing but options
    # should be in here.
    assert documented - real == set(), f"documented but not accepted: {documented - real}"
    assert real - documented == set(), f"accepted but not documented: {real - documented}"


def test_every_documented_error_code_is_one_we_raise(reference):
    from app import errors

    source = Path(errors.__file__).read_text()
    app_dir = Path(errors.__file__).parent
    everything = source + "".join(
        path.read_text() for path in sorted(app_dir.rglob("*.py"))
    )
    for code in re.findall(r'code:\s*"([a-z_]+)"', reference):
        assert f'"{code}"' in everything, f"documented error code never raised: {code}"


def test_the_generated_typescript_types_are_current():
    """`packages/shared/types.ts` is checked in, so it can go stale between
    a schema change and someone remembering to regenerate it. This is the
    reminder."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "packages" / "shared" / "generate.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or "types.ts is stale — run `make types`"
