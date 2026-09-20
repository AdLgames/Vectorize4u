"""§4.1 worker hygiene and §4.2 queue lanes.

Every setting here is a scar. In order:

- `worker_max_tasks_per_child = 25` — OpenCV/NumPy/Pillow fragment memory.
  Without recycling, RSS climbs until the box OOMs at 3am.
- `task_acks_late` + `task_reject_on_worker_lost` — a killed worker requeues
  rather than silently dropping a paid job.
- `worker_prefetch_multiplier = 1` — one task at a time per process, so a
  slow file does not sit behind a prefetched queue.
- `visibility_timeout = 600` — comfortably above the 60 s job timeout, so
  Redis never redelivers a task that is still running.
- `--without-gossip --without-mingle` (see the CLI args below) to cut broker
  chatter.

Late acks plus requeue-on-loss means an image that kills its worker is
redelivered forever. The delivery cap in `tasks.py` is the guard.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.config import settings
from celery import Celery
from celery.signals import worker_ready
from kombu import Queue

log = logging.getLogger("vectorize.worker")

QUEUE_PREVIEW = "queue_preview"
QUEUE_SYNC = "queue_sync"
QUEUE_BATCH = "queue_batch"

# Three pools, no sharing. Batch work runs on its own capped pool so it
# cannot starve the interactive lanes (§4.2).
QUEUES = (
    Queue(QUEUE_PREVIEW, routing_key=QUEUE_PREVIEW),
    Queue(QUEUE_SYNC, routing_key=QUEUE_SYNC),
    Queue(QUEUE_BATCH, routing_key=QUEUE_BATCH),
)

celery_app = Celery("vectorize-worker", broker=settings().redis_url, backend=None)

celery_app.conf.update(
    task_queues=QUEUES,
    task_default_queue=QUEUE_SYNC,
    task_routes={
        "worker.tasks.vectorize_job": {"queue": QUEUE_SYNC},
        "worker.tasks.build_batch_zip": {"queue": QUEUE_BATCH},
        "worker.tasks.sweep_expired": {"queue": QUEUE_BATCH},
        "worker.tasks.deliver_webhook": {"queue": QUEUE_BATCH},
    },
    worker_max_tasks_per_child=25,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=180,
    task_soft_time_limit=120,
    broker_transport_options={
        "visibility_timeout": 600,
        "queue_order_strategy": "priority",
    },
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # §8: the sweeper. R2 lifecycle rules on the free/ and paid/
        # prefixes are the backstop if this ever stops running.
        "sweep-expired": {
            "task": "worker.tasks.sweep_expired",
            "schedule": 900.0,
        },
    },
)

# How many times one job may be delivered before we stop trying (§4.1).
MAX_DELIVERIES = int(os.environ.get("VEC_MAX_DELIVERIES", "3"))


@worker_ready.connect  # type: ignore[misc]
def _report_environment(sender: Any = None, **_: Any) -> None:
    """Say out loud what this machine actually is, once, at startup.

    Three things here are assumptions everywhere else in the system, and
    all three are properties of the host rather than of the code:

    - **Which lanes this worker consumes.** Three pools, no sharing (§4.2).
      A worker that quietly took every queue would satisfy every test and
      break the preview guarantee in production.
    - **What isolation actually applied.** `sandbox_mode()` reports what the
      host allowed, not what we asked for — cgroup control inside a
      Firecracker VM is exactly the thing not to assume (§3.5).
    - **Which tracer binaries are on this PATH.** A tracer bump moves every
      benchmark score, so the version that produced a given job has to be
      recoverable from its logs rather than from someone's memory.
    """
    from engine.sandbox import sandbox_mode

    log.info("worker lanes: %s", ", ".join(_consumed_queues(sender)) or "(none)")
    log.info("sandbox mode: %s", sandbox_mode())
    for name, env_var in (
        ("vtracer", "ENGINE_VTRACER_BIN"),
        ("resvg", "ENGINE_RESVG_BIN"),
        ("potrace", "ENGINE_POTRACE_BIN"),
    ):
        log.info("tracer %s: %s", name, _binary_version(name, env_var))


def _consumed_queues(sender: Any) -> list[str]:
    """The lanes this worker is actually consuming, not the declared set.

    `task_queues` lists all three lanes in every process — it is the
    declaration. What a given machine consumes comes from `-Q`, and that is
    the number that matters, because a worker taking every lane is how a
    500-file batch ends up delaying previews.
    """
    try:
        return sorted(str(name) for name in sender.app.amqp.queues.consume_from)
    except Exception:  # pragma: no cover - depends on the celery internals
        declared = sorted(q.name for q in celery_app.conf.task_queues or ())
        return [f"{name} (declared; -Q not readable)" for name in declared]


def _binary_version(name: str, env_var: str) -> str:
    import subprocess

    from engine.sandbox import MissingBinary, resolve_binary

    try:
        path = resolve_binary(name, env_var)
    except MissingBinary:
        return "NOT FOUND"
    for flag in ("--version", "-v"):
        try:
            done = subprocess.run([path, flag], capture_output=True, timeout=5, text=True)
        except (OSError, subprocess.SubprocessError):
            continue
        output = (done.stdout or done.stderr).strip().splitlines()
        if output:
            return f"{output[0]} ({path})"
    return path
