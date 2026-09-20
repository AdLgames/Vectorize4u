"""Dispatch to the worker's three lanes (§4.2).

Three pools, no sharing. A 500-file batch must never block a preview: batch
work runs on its own capped pool so it cannot starve the interactive lanes.

The API never imports the worker's task code — it sends by name, so the
service can deploy without the engine or the tracer binaries installed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from app.config import settings

Lane = Literal["preview", "sync", "batch"]

QUEUE_NAMES: dict[Lane, str] = {
    "preview": "queue_preview",
    "sync": "queue_sync",
    "batch": "queue_batch",
}

# Higher is more urgent. Interactive preview is the sales pitch (§4.2).
QUEUE_PRIORITY: dict[Lane, int] = {"preview": 9, "sync": 5, "batch": 1}

TASK_NAME = "worker.tasks.vectorize_job"
ZIP_TASK_NAME = "worker.tasks.build_batch_zip"


@lru_cache(maxsize=1)
def _app() -> Any:
    from celery import Celery

    cfg = settings()
    client = Celery("vectorize-api", broker=cfg.redis_url, backend=None)
    client.conf.task_default_queue = QUEUE_NAMES["sync"]
    return client


class Dispatcher:
    """Indirection so tests can run the pipeline inline."""

    def send(self, job_id: str, lane: Lane) -> str | None:
        result = _app().send_task(
            TASK_NAME,
            args=[job_id],
            queue=QUEUE_NAMES[lane],
            priority=QUEUE_PRIORITY[lane],
        )
        return str(result.id)

    def send_zip(self, batch_id: str) -> str | None:
        result = _app().send_task(
            ZIP_TASK_NAME, args=[batch_id], queue=QUEUE_NAMES["batch"], priority=1
        )
        return str(result.id)


class InlineDispatcher(Dispatcher):
    """Run jobs synchronously in-process.

    Used by the test suite and by `VEC_INLINE_WORKER=1` local development, so
    the whole request path can be exercised without a broker. Never used in
    production: the point of the worker is that long jobs do not block HTTP.
    """

    def send(self, job_id: str, lane: Lane) -> str | None:
        from worker.tasks import run_job_inline

        run_job_inline(job_id)
        return None

    def send_zip(self, batch_id: str) -> str | None:
        from worker.tasks import build_zip_inline

        build_zip_inline(batch_id)
        return None


_dispatcher: Dispatcher | None = None


def dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        # VEC_INLINE_WORKER=1 runs jobs in the request thread. For local
        # development only: the entire point of the worker is that long jobs
        # do not block HTTP, so this is refused in production.
        import os

        if os.environ.get("VEC_INLINE_WORKER") == "1":
            if settings().is_production:
                raise RuntimeError("VEC_INLINE_WORKER is refused in production")
            _dispatcher = InlineDispatcher()
        else:
            _dispatcher = Dispatcher()
    return _dispatcher


def set_dispatcher(value: Dispatcher | None) -> None:
    global _dispatcher
    _dispatcher = value
