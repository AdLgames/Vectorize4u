"""Let the browser PUT straight to R2 (§4.3).

Without this, the product does not work at all, and says so in the least
useful way available. The browser gets a presigned URL and PUTs the file
to R2 itself — uploads never pass through Vercel, whose body cap is about
4.5 MB against a 25 MB logo. A cross-origin PUT needs the *bucket* to
allow this site's origin; nothing the API does can grant it.

When the bucket has no CORS policy the browser refuses the request before
sending it, and `fetch` rejects rather than returning a response. That
rejection is not an HTTP error anywhere: no status, no body, nothing in
any server log, because the request was never made. On the site it
surfaces as "Something went wrong. Please try again." for every file, of
any size or format.

It is invisible to a check that uploads from a script, too — CORS is a
browser rule, and Python does not enforce it. `scripts/verify_live.py`
sends the preflight explicitly for exactly that reason.

    python infra/r2_cors.py --check
    python infra/r2_cors.py --apply --origin https://vectorize4u.vercel.app

Pass --origin once per site that uploads: production, and any preview
deployment you want to be able to test from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r2_lifecycle import client_and_bucket

# GET and HEAD as well as PUT: the same bucket serves signed download URLs
# for finished files, and a browser fetching one cross-origin needs the
# same permission.
METHODS = ["PUT", "GET", "HEAD"]

# Content-Type is the one the presigned PUT actually sends, and it is
# signed into the URL, so it cannot be dropped. A blanket "*" would work
# and says less about what is expected.
REQUEST_HEADERS = ["content-type"]

# The browser reads neither on this path, but ETag is what a client would
# use to verify an upload landed intact, and it costs nothing to expose.
EXPOSE_HEADERS = ["ETag"]

MAX_AGE_SECONDS = 3600


def rules(origins: list[str]) -> dict:
    return {
        "CORSRules": [
            {
                "AllowedOrigins": origins,
                "AllowedMethods": METHODS,
                "AllowedHeaders": REQUEST_HEADERS,
                "ExposeHeaders": EXPOSE_HEADERS,
                "MaxAgeSeconds": MAX_AGE_SECONDS,
            }
        ]
    }


def _current(client, bucket):  # type: ignore[no-untyped-def]
    try:
        return client.get_bucket_cors(Bucket=bucket).get("CORSRules", [])
    except Exception as exc:  # botocore raises NoSuchCORSConfiguration
        if "NoSuchCORSConfiguration" in str(exc) or "NoSuchCORSConfig" in str(exc):
            return []
        raise


def check(origins: list[str]) -> int:
    client, bucket = client_and_bucket()
    live = _current(client, bucket)
    if not live:
        print(f"{bucket}: no CORS policy — every browser upload is blocked")
        return 1

    print(json.dumps(live, indent=2, default=str))

    allowed = {origin for rule in live for origin in rule.get("AllowedOrigins", [])}
    methods = {method.upper() for rule in live for method in rule.get("AllowedMethods", [])}

    problems = []
    if "PUT" not in methods and "*" not in methods:
        problems.append("PUT is not allowed, so the browser cannot upload")
    for origin in origins:
        if origin not in allowed and "*" not in allowed:
            problems.append(f"{origin} is not an allowed origin")

    for problem in problems:
        print(f"  ! {problem}")
    return 1 if problems else 0


def apply(origins: list[str]) -> int:
    if not origins:
        raise SystemExit("--apply needs at least one --origin")
    client, bucket = client_and_bucket()
    client.put_bucket_cors(Bucket=bucket, CORSConfiguration=rules(origins))
    print(f"{bucket}: CORS written for {', '.join(origins)}")
    return check(origins)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--origin",
        action="append",
        default=[],
        help="a site allowed to upload. Repeat for more than one.",
    )
    args = parser.parse_args()
    return apply(args.origin) if args.apply else check(args.origin)


if __name__ == "__main__":
    raise SystemExit(main())
