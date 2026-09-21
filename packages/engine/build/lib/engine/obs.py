"""Observability shim.

The engine must stay importable with no web dependencies, so Sentry is
optional at import time. When it is present, every subprocess call becomes a
span carrying argv, exit code and full stderr — §3.5 makes that a hard
requirement, because tracer failures are invisible otherwise.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

log = logging.getLogger("engine")

try:  # pragma: no cover - depends on deployment
    import sentry_sdk  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    sentry_sdk = None  # type: ignore[assignment]


@contextlib.contextmanager
def span(op: str, description: str = "", **data: Any) -> Iterator[dict[str, Any]]:
    payload: dict[str, Any] = dict(data)
    if sentry_sdk is None:
        try:
            yield payload
        finally:
            log.debug("%s %s %s", op, description, payload)
        return
    with sentry_sdk.start_span(op=op, description=description) as s:  # pragma: no cover
        try:
            yield payload
        finally:
            for k, v in payload.items():
                s.set_data(k, v)
