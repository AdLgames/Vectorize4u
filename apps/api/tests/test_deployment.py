"""The deployment's invariants (§4.2, §8, §11).

None of this can be verified by running the application, and all of it is
the kind of thing that drifts silently: a version pinned in CI but not in
the image, a lifecycle window that no longer covers the retention setting
it is meant to back up, a worker image that would happily consume every
lane. So it is checked here, where a failing test is cheaper than a
surprise in production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "infra"


@pytest.fixture(scope="module")
def pinned() -> dict[str, str]:
    """The tracer versions, from the one file that holds them."""
    values = {}
    for line in (INFRA / "tracers.env").read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_the_tracer_versions_are_pinned_everywhere(pinned):
    """A tracer bump moves every benchmark score. If CI and the image can
    disagree about the version, the score you measured is not the score
    your customers get."""
    assert pinned["VTRACER_VERSION"] and pinned["RESVG_VERSION"]

    worker = (INFRA / "Dockerfile.worker").read_text()
    assert f'ARG VTRACER_VERSION={pinned["VTRACER_VERSION"]}' in worker
    assert f'ARG RESVG_VERSION={pinned["RESVG_VERSION"]}' in worker

    for workflow in ("engine.yml", "service.yml"):
        ci = (ROOT / ".github" / "workflows" / workflow).read_text()
        assert f'cargo install vtracer --version {pinned["VTRACER_VERSION"]}' in ci, workflow
        assert f'cargo install resvg --version {pinned["RESVG_VERSION"]}' in ci, workflow
        # The cache key has to move with the versions, or a bump is served
        # the old binaries out of the cache and nothing appears to change.
        assert f'vtracer{pinned["VTRACER_VERSION"]}' in ci, workflow
        assert f'resvg{pinned["RESVG_VERSION"]}' in ci, workflow


def test_the_worker_image_refuses_to_run_without_a_lane():
    """Three pools, no sharing (§4.2). An image that defaults to every
    queue passes every test and breaks the preview guarantee in
    production, so the default is a failure to start."""
    worker = (INFRA / "Dockerfile.worker").read_text()
    assert "${QUEUES:?" in worker, "QUEUES must be required, not defaulted"
    assert "--without-gossip" in worker and "--without-mingle" in worker


def test_each_lane_gets_its_own_app():
    lanes = {
        "fly.worker-preview.toml": "queue_preview",
        "fly.worker-sync.toml": "queue_sync",
        "fly.worker-batch.toml": "queue_batch",
    }
    seen = set()
    for filename, queue in lanes.items():
        config = (INFRA / filename).read_text()
        assert f'QUEUES = "{queue}"' in config
        app = re.search(r'^app = "([^"]+)"', config, re.M)
        assert app, filename
        assert app.group(1) not in seen, "two lanes sharing one app is one pool, not two"
        seen.add(app.group(1))


def test_the_api_never_scales_to_zero():
    """A cold start inside the 8-second hold window turns a synchronous
    conversion into a timeout."""
    config = (INFRA / "fly.api.toml").read_text()
    assert "min_machines_running = 1" in config


def test_migrations_run_once_per_deploy_not_once_per_machine():
    config = (INFRA / "fly.api.toml").read_text()
    assert 'release_command = "python -m alembic upgrade head"' in config


def _images() -> dict[str, str]:
    """The API image is at the repository root under its plain name, so
    that `fly launch` and every other detector finds it; the worker's is
    in infra/ because it is never the one a detector should pick."""
    return {
        "Dockerfile": (ROOT / "Dockerfile").read_text(),
        "Dockerfile.worker": (INFRA / "Dockerfile.worker").read_text(),
    }


def test_the_api_image_is_where_build_detection_looks():
    assert (ROOT / "Dockerfile").exists(), "fly launch cannot detect a build without this"
    assert "uvicorn" in (ROOT / "Dockerfile").read_text()


def test_the_images_do_not_run_as_root():
    for name, body in _images().items():
        assert "USER vectorize" in body, name
        assert body.index("USER vectorize") < body.index("CMD"), name


def test_potrace_is_a_binary_and_not_a_library():
    """GPLv2. It is invoked as a subprocess and never linked (docs/licensing.md)."""
    worker = (INFRA / "Dockerfile.worker").read_text()
    assert "potrace \\" in worker or "potrace\n" in worker
    assert "libpotrace" not in worker


def test_the_lifecycle_rules_outlive_the_retention_settings():
    """The bucket is the backstop for a dead sweeper — it must not be the
    thing that deletes first. If it fired before `expires_at`, the API
    would hand out signed URLs for objects that are already gone."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("r2_lifecycle", INFRA / "r2_lifecycle.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from app.config import Settings

    defaults = Settings()
    windows = {
        rule["Filter"]["Prefix"]: rule["Expiration"]["Days"] for rule in module.RULES["Rules"]
    }

    free_days = defaults.retention_free_hours / 24
    assert windows["free/"] > free_days, (
        f"free/ expires at {windows['free/']}d but we promise {free_days}d — "
        "the bucket would delete before the sweeper does"
    )
    assert windows["paid/"] > defaults.retention_paid_days
    # And not so long that the promise becomes meaningless.
    assert windows["free/"] <= free_days + 2
    assert windows["paid/"] <= defaults.retention_paid_days + 7


def test_the_lifecycle_prefixes_are_the_ones_we_write_under():
    import importlib.util

    from app.storage import object_key

    spec = importlib.util.spec_from_file_location("r2_lifecycle", INFRA / "r2_lifecycle.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    prefixes = {rule["Filter"]["Prefix"] for rule in module.RULES["Rules"]}
    for tier in ("free", "paid"):
        key = object_key(tier, "source", "job_1", "source.bin")  # type: ignore[arg-type]
        assert any(key.startswith(prefix) for prefix in prefixes), key
