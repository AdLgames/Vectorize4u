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

import os

from app.config import settings
from celery import Celery
from kombu import Queue

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
