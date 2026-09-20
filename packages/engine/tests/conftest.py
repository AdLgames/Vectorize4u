from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "benchmarks"))

import fixtures  # noqa: E402


@pytest.fixture(scope="session")
def fx():
    return fixtures


def _have(binary: str) -> bool:
    import shutil

    return shutil.which(binary) is not None


needs_vtracer = pytest.mark.skipif(not _have("vtracer"), reason="vtracer not installed")
needs_potrace = pytest.mark.skipif(not _have("potrace"), reason="potrace not installed")
needs_resvg = pytest.mark.skipif(not _have("resvg"), reason="resvg not installed")
