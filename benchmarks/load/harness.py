"""Bring up a real stack: API, two worker pools, a broker, a database.

Everything else in this repository runs the worker inline, which is the
one configuration in which "a batch never delays a preview" cannot fail.
This is the opposite: separate processes, a real broker, and the queue
routing from §4.2 actually doing the routing.

Expects `VEC_DATABASE_URL` and `VEC_REDIS_URL` to point at something
running, and migrations already applied. `make load-test` does both.
"""

from __future__ import annotations

import io
import os
import signal
import subprocess
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "apps" / "api"
WORKER_DIR = ROOT / "apps" / "worker"


def tiny_png() -> bytes:
    """A small flat logo-ish image: fast to trace, and real enough that the
    engine takes its normal path rather than an early-out."""
    import numpy as np
    from PIL import Image

    canvas = np.full((96, 96, 4), 255, dtype=np.uint8)
    canvas[18:78, 18:78] = (0, 136, 168, 255)
    canvas[34:62, 34:62] = (255, 255, 255, 255)
    canvas[44:52, 26:70] = (192, 30, 98, 255)
    buffer = io.BytesIO()
    Image.fromarray(canvas).save(buffer, format="PNG")
    return buffer.getvalue()


def _cpu_split() -> tuple[list[int], list[int]] | None:
    """Cores for the preview pool and the batch pool, or None if too few.

    §4.2 says three pools, no sharing, and in production they are three
    separate Fly apps — separate machines, separate CPUs. On one box the
    queues are still separate but the *cores* are not, and that turns out
    to be enough to break the guarantee on its own (see the report in
    docs/architecture.md). Pinning each pool to its own cores is the
    closest a single machine gets to the deployed shape.
    """
    count = os.cpu_count() or 1
    if count < 4:
        return None
    half = count // 2
    return list(range(half)), list(range(half, count))


class Stack:
    """The API and two worker pools, started and stopped together."""

    def __init__(self, *, port: int = 8123, pin_cpus: bool = True) -> None:
        self.pin_cpus = pin_cpus
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.processes: list[tuple[str, subprocess.Popen[bytes]]] = []
        self.storage_dir = Path(os.environ.get("VEC_STORAGE_LOCAL_DIR", "/tmp/vec-load-storage"))
        self.client = httpx.Client(timeout=120.0)

    # -- lifecycle ------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "VEC_ENVIRONMENT": "dev",
                "VEC_DEV_AUTH_ENABLED": "1",
                "VEC_STORAGE_BACKEND": "local",
                "VEC_STORAGE_LOCAL_DIR": str(self.storage_dir),
                "VEC_PUBLIC_API_URL": self.base_url,
                # The point of the exercise: no inline worker anywhere.
                "VEC_INLINE_WORKER": "0",
                # The preview limit is an abuse guard (§8), not part of
                # what is under test — one client firing previews as fast
                # as it can is exactly what it exists to stop. Raised here
                # so the measurement is of the queue, not of the limiter.
                "VEC_PREVIEW_LIMIT_SIGNED_IN_PER_HOUR": "100000",
                "VEC_PREVIEW_LIMIT_ANONYMOUS_PER_HOUR": "100000",
                "VEC_TILE_LIMIT_PER_HOUR": "100000",
                "PYTHONUNBUFFERED": "1",
            }
        )
        return env

    def __enter__(self) -> Self:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        python = str(ROOT / ".venv" / "bin" / "python")
        env = self._env()

        self._spawn(
            "api",
            [python, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=API_DIR,
            env=env,
        )
        # Three lanes, three pools (§4.2). The preview pool exists to answer
        # in under two seconds and must never be handed batch work.
        split = _cpu_split() if self.pin_cpus else None
        preview_cores, batch_cores = split if split else ([], [])

        # The preview lane runs with the recycle interval it is deployed
        # with (infra/fly.worker-preview.toml). At the default 25 every
        # 25th preview pays for an interpreter warm-up, and since the two
        # phases of this test take different numbers of previews, that
        # lands at a different percentile in each — which looks exactly
        # like batch interference and is not.
        preview_env = dict(env, VEC_MAX_TASKS_PER_CHILD="200")
        self._spawn(
            "worker-preview",
            self._pin(preview_cores)
            + [python, "-m", "celery", "-A", "worker.celery_app:celery_app", "worker",
               "-Q", "queue_preview,queue_sync",
               "--concurrency", str(max(1, len(preview_cores) or 2)),
               "--without-gossip", "--without-mingle", "--loglevel", "warning"],
            cwd=WORKER_DIR,
            env=preview_env,
        )
        self._spawn(
            "worker-batch",
            self._pin(batch_cores)
            + [python, "-m", "celery", "-A", "worker.celery_app:celery_app", "worker",
               "-Q", "queue_batch",
               "--concurrency", str(max(1, len(batch_cores) or 2)),
               "--without-gossip", "--without-mingle", "--loglevel", "warning"],
            cwd=WORKER_DIR,
            env=env,
        )
        self._wait_for_api()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        tb: TracebackType | None = None,
    ) -> None:
        self.client.close()
        for _name, process in reversed(self.processes):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        deadline = time.time() + 15
        for _name, process in self.processes:
            while process.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            if process.poll() is None:
                process.kill()

    @staticmethod
    def _pin(cores: list[int]) -> list[str]:
        if not cores:
            return []
        return ["taskset", "-c", ",".join(str(core) for core in cores)]

    def _spawn(self, name: str, argv: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        # The handle outlives this function on purpose: it is the process's
        # log for as long as the process runs.
        log = open(f"/tmp/vec-load-{name}.log", "wb")  # noqa: SIM115
        self.processes.append(
            (name, subprocess.Popen(argv, cwd=cwd, env=env, stdout=log, stderr=log))
        )

    def _wait_for_api(self, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.client.get(f"{self.base_url}/health", timeout=2.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            for name, process in self.processes:
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited early — see /tmp/vec-load-{name}.log")
            time.sleep(0.3)
        raise RuntimeError("the API never came up")

    def worker_rss(self) -> dict[str, float]:
        """Resident memory per worker process tree, in MB.

        §13 wants RSS flat across a long run; this is the same number, read
        at the end of a shorter one.
        """
        out: dict[str, float] = {}
        for name, process in self.processes:
            if not name.startswith("worker"):
                continue
            total = 0.0
            for pid in self._tree(process.pid):
                try:
                    status = Path(f"/proc/{pid}/status").read_text()
                except OSError:
                    continue
                for line in status.splitlines():
                    if line.startswith("VmRSS:"):
                        total += float(line.split()[1]) / 1024.0
            out[name] = round(total, 1)
        return out

    @staticmethod
    def _tree(pid: int) -> list[int]:
        pids = [pid]
        try:
            children = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        except OSError:
            return pids
        for child in children:
            pids.extend(Stack._tree(int(child)))
        return pids

    # -- the API, as a client sees it -----------------------------------

    def sign_in(self, email: str, *, plan: str = "free") -> str:
        response = self.client.post(f"{self.base_url}/v1/dev/session", json={"email": email})
        response.raise_for_status()
        body = response.json()
        token = str(body["access_token"])
        # The dev route mints a token; the account row is created by the
        # auth layer on the first authenticated request. So ask for the
        # account before touching its plan, or the UPDATE finds nothing
        # and the caller silently stays on `free`.
        self.client.get(f"{self.base_url}/v1/account", headers=self._auth(token)).raise_for_status()
        if plan != "free":
            self._set_plan(body["user_id"], plan)
        return token

    def _set_plan(self, user_id: str, plan: str) -> None:
        """Straight to the database: Stripe is not part of this test."""
        import sys

        sys.path.insert(0, str(API_DIR))
        from sqlalchemy import create_engine, text

        url = os.environ["VEC_DATABASE_URL"]
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET plan = :plan WHERE id = :id"),
                {"plan": plan, "id": user_id},
            )
        engine.dispose()

    def _auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _upload(self, data: bytes, token: str) -> str:
        created = self.client.post(
            f"{self.base_url}/v1/uploads",
            json={"content_type": "image/png", "content_length": len(data)},
            headers=self._auth(token),
        )
        created.raise_for_status()
        slot = created.json()
        put = self.client.put(
            slot["put_url"], content=data, headers={"Content-Type": "image/png"}
        )
        put.raise_for_status()
        return str(slot["upload_id"])

    def health(self) -> float:
        started = time.perf_counter()
        self.client.get(f"{self.base_url}/health").raise_for_status()
        return time.perf_counter() - started

    def preview(self, data: bytes, token: str) -> float:
        """One preview, end to end, in seconds — what a visitor waits."""
        started = time.perf_counter()
        upload_id = self._upload(data, token)
        response = self.client.post(
            f"{self.base_url}/v1/preview",
            json={"upload_id": upload_id, "options": {"quality_tier": "fast"}},
            headers=self._auth(token),
        )
        response.raise_for_status()
        body = response.json()
        # A 202 means the hold window expired; poll, because the number
        # that matters is when the *user* sees it, not when we gave up.
        while body["status"] not in ("complete", "failed"):
            time.sleep(0.15)
            polled = self.client.get(
                f"{self.base_url}/v1/jobs/{body['id']}", headers=self._auth(token)
            )
            polled.raise_for_status()
            body = polled.json()
        return time.perf_counter() - started

    def submit_batch(self, data: bytes, count: int, token: str) -> str:
        created = self.client.post(
            f"{self.base_url}/v1/batch",
            json={"count": count, "content_type": "image/png", "content_length": len(data)},
            headers=self._auth(token),
        )
        created.raise_for_status()
        batch = created.json()
        for slot in batch["slots"]:
            self.client.put(
                slot["put_url"], content=data, headers={"Content-Type": "image/png"}
            ).raise_for_status()
        started = self.client.post(
            f"{self.base_url}/v1/batch/{batch['batch_id']}/start",
            json={"upload_ids": [s["upload_id"] for s in batch["slots"]]},
            headers=self._auth(token),
        )
        started.raise_for_status()
        return str(batch["batch_id"])

    def batch_state(self, batch_id: str, token: str) -> dict[str, Any]:
        response = self.client.get(
            f"{self.base_url}/v1/batch/{batch_id}", headers=self._auth(token)
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body


__all__ = ["Stack", "tiny_png"]
