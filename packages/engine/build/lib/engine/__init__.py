"""Raster → vector engine.

Pure library: no web framework, no database, no cloud SDK. It must stay
importable and benchmarkable offline (§3).
"""

from __future__ import annotations

from engine.version import ENGINE_VERSION

__all__ = ["ENGINE_VERSION"]
