"""Prove a deployed stack actually converts an image (§13).

`/health` says the API process booted. It says nothing about whether the
worker is consuming its lane, whether Redis is reachable, whether R2
accepts the presigned PUT, or whether the tracer binaries made it into
the image. This walks the anonymous preview path end to end, which
touches all of them:

    POST /v1/uploads  ->  PUT to R2  ->  POST /v1/preview
                      ->  poll /v1/jobs/{id}  ->  GET the preview SVG

No credentials: `/v1/preview` is anonymous-friendly and rate-limited by
IP (§7), so this runs against staging without a Supabase project or an
API key. Standard library only, so it runs on a bare CI runner.

    python scripts/verify_live.py https://vectorize4u-api.fly.dev

Exits non-zero with the failing step named. That is the point: it is a
gate, not a report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE = REPO / "benchmarks" / "corpus" / "logo_flat_small.png"

# A preview is a real trace: the search engine runs, and a cold worker has
# to pull the image first. Generous, because a false red here costs more
# than a slow green.
JOB_TIMEOUT_S = 180.0
TERMINAL = {"complete", "failed", "expired"}


class StepFailed(Exception):
    pass


def _request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, data=body, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        # An error body is the most useful thing on the screen; the API
        # answers problem+json (§6), so keep it rather than raising bare.
        return error.code, error.read(), dict(error.headers or {})


def _json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    status, raw, _ = _request(method, url, body=body, headers=headers)
    try:
        return status, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise StepFailed(
            f"{method} {url} -> {status}, and the body was not JSON: {raw[:400]!r}"
        )


def _expect(status: int, wanted: int, what: str, detail: object = "") -> None:
    if status != wanted:
        raise StepFailed(f"{what}: expected {wanted}, got {status}. {detail}")


def health(base: str) -> None:
    status, body = _json("GET", f"{base}/health")
    _expect(status, 200, "/health", body)
    if body.get("status") != "ok":
        raise StepFailed(f"/health answered, but not ok: {body}")
    print(f"  health      ok  (environment={body.get('environment')})")


def upload(base: str, image: bytes) -> str:
    status, slot = _json(
        "POST",
        f"{base}/v1/uploads",
        {"content_type": "image/png", "content_length": len(image)},
    )
    _expect(status, 200, "POST /v1/uploads", slot)

    put_status, put_body, _ = _request(
        slot.get("method", "PUT"),
        slot["put_url"],
        body=image,
        headers=slot.get("headers") or {},
    )
    if put_status not in (200, 201, 204):
        # Almost always the R2 credentials or the bucket name, not the code.
        raise StepFailed(
            f"the presigned PUT was rejected with {put_status}: {put_body[:400]!r}\n"
            "      check VEC_R2_* on the API app"
        )
    print(f"  upload      ok  ({len(image)} bytes -> {slot['upload_id']})")
    return str(slot["upload_id"])


def preview(base: str, upload_id: str) -> str:
    status, job = _json("POST", f"{base}/v1/preview", {"upload_id": upload_id})
    if status not in (200, 202):
        raise StepFailed(f"POST /v1/preview: expected 200 or 202, got {status}. {job}")
    print(f"  preview     ok  ({job['id']}, {status} {job['status']})")
    return str(job["id"])


def wait(base: str, job_id: str) -> dict:
    deadline = time.monotonic() + JOB_TIMEOUT_S
    delay = 1.0
    last = ""
    while time.monotonic() < deadline:
        status, job = _json("GET", f"{base}/v1/jobs/{job_id}")
        _expect(status, 200, f"GET /v1/jobs/{job_id}", job)
        if job["status"] != last:
            print(f"  job         {job['status']}")
            last = job["status"]
        if job["status"] in TERMINAL:
            return job
        time.sleep(delay)
        delay = min(delay * 1.4, 5.0)
    raise StepFailed(
        f"the job was still {last!r} after {JOB_TIMEOUT_S:.0f}s.\n"
        "      a preview that never leaves 'queued' means no worker is on "
        "queue_preview, or the broker is unreachable"
    )


def check(job: dict) -> None:
    if job["status"] != "complete":
        raise StepFailed(
            f"the job finished {job['status']}: error_code={job.get('error_code')!r}"
        )
    quality = job.get("quality")
    if not quality:
        raise StepFailed(
            "the job completed without a score, so the engine did not measure it"
        )
    for field in ("total", "fidelity", "score_version"):
        if quality.get(field) in (None, ""):
            raise StepFailed(f"the score is missing {field}: {quality}")
    print(
        f"  quality     total={quality['total']:.4f} fidelity={quality['fidelity']:.4f} "
        f"paths={quality['paths']} nodes={quality['nodes']} ({quality['score_version']})"
    )
    if job.get("classification"):
        print(f"  classified  {job['classification']}")


def fetch_preview_tile(base: str, job: dict) -> None:
    """Fetch the preview and assert it is a real raster tile.

    Deliberately not the SVG: §7.4 keeps the SVG server-side until the job
    is unlocked, because an SVG in the DOM *is* the download. The tile is
    rasterised on demand from the stored SVG, so a valid PNG coming back
    proves more than the SVG would — the trace is on disk, and resvg can
    render it.
    """
    path = job.get("preview_url")
    if not path:
        raise StepFailed("a complete job exposed no preview_url")
    url = path if path.startswith("http") else f"{base}{path}"
    status, raw, headers = _request("GET", url)
    _expect(status, 200, f"GET {path}", raw[:200])

    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        kind = {k.lower(): v for k, v in headers.items()}.get("content-type")
        raise StepFailed(
            f"the preview tile is not a PNG (content-type={kind!r}, "
            f"first bytes {raw[:16]!r})"
        )
    # A tile that renders nothing still encodes as a valid, and very
    # small, PNG. Anything real is several KB.
    if len(raw) < 1024:
        raise StepFailed(
            f"the preview tile is only {len(raw)} bytes, which is an empty render"
        )
    print(f"  preview png ok  ({len(raw)} bytes, watermarked tile)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="e.g. https://vectorize4u-api.fly.dev")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    image = args.image.read_bytes()
    print(f"verifying {base} with {args.image.name}")

    try:
        health(base)
        job_id = preview(base, upload(base, image))
        job = wait(base, job_id)
        check(job)
        fetch_preview_tile(base, job)
    except StepFailed as failure:
        print(f"\nFAILED: {failure}", file=sys.stderr)
        return 1

    print("\nthe deployed stack converts an image end to end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
