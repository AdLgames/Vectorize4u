"""§3.5 — the 400/500 split is what the service's retry logic keys on."""

from __future__ import annotations

import sys

import pytest

from engine.errors import MissingBinary, TracerCrash, TracerFailed
from engine.sandbox import resolve_binary, run, sandbox_mode


def test_sandbox_mode_is_recorded():
    assert sandbox_mode() in ("bwrap", "unshare", "rlimit-only")


def test_missing_binary_is_its_own_error():
    with pytest.raises(MissingBinary):
        resolve_binary("definitely-not-a-real-binary", "ENGINE_NOPE_BIN")


def test_nonzero_exit_with_stderr_raises_tracer_failed():
    with pytest.raises(TracerFailed):
        run([sys.executable, "-c", "import sys; sys.stderr.write('bad input'); sys.exit(3)"])


def test_signal_death_is_a_crash():
    with pytest.raises(TracerCrash):
        run([sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)"])


def test_timeout_is_a_crash():
    with pytest.raises(TracerCrash):
        run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)


def test_silent_nonzero_exit_is_a_crash():
    with pytest.raises(TracerCrash):
        run([sys.executable, "-c", "raise SystemExit(4)"])


def test_successful_run_returns_stdout():
    result = run([sys.executable, "-c", "print('hello')"])
    assert result.stdout.strip() == b"hello"
    assert result.returncode == 0
