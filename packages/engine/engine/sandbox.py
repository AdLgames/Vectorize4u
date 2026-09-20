"""§3.5 Subprocess sandboxing and observability.

Both tracers and the rasterizer run as subprocesses so that a crash, a hang
or a memory explosion is contained and attributable. The minimum
implementation the spec asks for is `prlimit` (RLIMIT_AS, RLIMIT_CPU) plus
`unshare -n`; `bubblewrap`/`nsjail` are used where the host allows them.

Do not assume cgroup control inside a Fly/Firecracker VM — capability is
probed at import time and recorded in `SANDBOX_MODE` so the runbook can say
what actually happened on a given host.
"""

from __future__ import annotations

import logging
import os
import resource
import shutil
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache

from engine import config
from engine.errors import MissingBinary, TracerCrash, TracerFailed

log = logging.getLogger("engine.sandbox")


@dataclass
class ProcResult:
    argv: list[str]
    returncode: int
    stdout: bytes
    stderr: str
    duration_ms: int


@lru_cache(maxsize=1)
def _net_isolation() -> list[str]:
    """Return an argv prefix that removes network access, if one works here."""
    if not config.SANDBOX_NETWORK:
        return []
    if shutil.which("bwrap"):
        probe = ["bwrap", "--unshare-net", "--ro-bind", "/", "/", "--dev", "/dev", "true"]
        if _probe(probe):
            return ["bwrap", "--unshare-net", "--ro-bind", "/", "/", "--dev", "/dev",
                    "--bind", "/tmp", "/tmp"]
    if shutil.which("unshare") and _probe(["unshare", "-n", "true"]):
        return ["unshare", "-n"]
    log.warning(
        "no network isolation available for tracer subprocesses; "
        "relying on host firewall (see docs/runbook.md)"
    )
    return []


def _probe(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def sandbox_mode() -> str:
    prefix = _net_isolation()
    return prefix[0] if prefix else "rlimit-only"


def _limits() -> None:  # pragma: no cover - runs in the forked child
    """Applied in the child between fork and exec."""
    mem = config.SUBPROCESS_MEMORY_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    except (ValueError, OSError):
        pass
    cpu = config.SUBPROCESS_CPU_S
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 2))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except (ValueError, OSError):
        pass
    os.setsid()


def resolve_binary(name: str, env_var: str) -> str:
    path = os.environ.get(env_var) or shutil.which(name)
    if not path:
        raise MissingBinary(f"{name} not found on PATH (set {env_var} to override)")
    return path


def run(
    argv: list[str],
    *,
    timeout: float | None = None,
    stdin: bytes | None = None,
    scratch_dir: str | None = None,
) -> ProcResult:
    """Run a sandboxed subprocess and map failures to the right error class.

    The two failure modes are kept apart deliberately (§3.5): a non-zero exit
    with parseable stderr is the *image's* fault (400 class); a signal, an
    empty output or a timeout is *ours* (500 class, alert, retry once).
    """
    timeout = timeout or config.CANDIDATE_TIMEOUT_S
    full = _net_isolation() + argv
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": scratch_dir or "/tmp",
        "TMPDIR": scratch_dir or "/tmp",
        "LANG": "C",
        # Pin thread counts: reproducible benchmarks need it, and N parallel
        # candidates each spawning N threads is how a 4-core box thrashes.
        "OMP_NUM_THREADS": "1",
        "RAYON_NUM_THREADS": "1",
    }
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            full,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            preexec_fn=_limits,
            env=env,
            cwd=scratch_dir or None,
        )
    except subprocess.TimeoutExpired as exc:
        raise TracerCrash(f"timeout after {timeout}s: {argv[0]}") from exc
    except OSError as exc:
        raise TracerCrash(f"could not start {argv[0]}: {exc}") from exc

    duration_ms = int((time.perf_counter() - started) * 1000)
    stderr = proc.stderr.decode("utf-8", "replace").strip()

    if proc.returncode < 0:
        # Killed by a signal: SIGSEGV/SIGABRT/SIGKILL(OOM). Ours to fix.
        raise TracerCrash(f"{argv[0]} died on signal {-proc.returncode}: {stderr[:500]}")
    if proc.returncode != 0:
        if stderr:
            raise TracerFailed(f"{argv[0]} exit {proc.returncode}: {stderr[:500]}")
        raise TracerCrash(f"{argv[0]} exit {proc.returncode} with no stderr")

    return ProcResult(
        argv=full,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )
