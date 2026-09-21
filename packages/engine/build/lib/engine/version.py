from __future__ import annotations

import os
import subprocess
from functools import lru_cache

SEMVER = "0.1.0"


@lru_cache(maxsize=1)
def _git_sha() -> str:
    override = os.environ.get("ENGINE_GIT_SHA")
    if override:
        return override[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


ENGINE_VERSION = f"{SEMVER}+{_git_sha()}"
