"""Apply the R2 lifecycle rules that back the retention promise (§8).

The sweeper in `app/retention.py` is what normally deletes expired work.
These rules are the backstop for the case that matters: a sweeper that
stopped running. Without them, "we delete your files after 24 hours" is a
claim that depends on a cron job nobody is watching — and it is the exact
guarantee a print shop under NDA is buying.

    python infra/r2_lifecycle.py --check    # show what is configured
    python infra/r2_lifecycle.py --apply    # write the rules

The two prefixes are the ones `storage.object_key` writes under, so the
tier a job ran as decides how long its bytes can possibly survive.

The windows are deliberately a day longer than the promise (2 days against
24 hours, 31 days against 30) so that the sweeper, not the bucket, is what
normally does the deleting — a lifecycle rule firing first would make
`expires_at` and reality disagree, and the API would hand out signed URLs
for objects that are already gone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

RULES = {
    "Rules": [
        {
            "ID": "free-tier-2-days",
            "Status": "Enabled",
            "Filter": {"Prefix": "free/"},
            "Expiration": {"Days": 2},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
        },
        {
            "ID": "paid-tier-31-days",
            "Status": "Enabled",
            "Filter": {"Prefix": "paid/"},
            "Expiration": {"Days": 31},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
        },
    ]
}


def client_and_bucket():
    from app.config import settings

    cfg = settings()
    if cfg.storage_backend != "r2":
        raise SystemExit("VEC_STORAGE_BACKEND is not 'r2' — nothing to configure")
    if not cfg.r2_bucket or not cfg.r2_endpoint_url:
        raise SystemExit("R2 bucket/endpoint are not configured")

    import boto3
    from botocore.config import Config

    return (
        boto3.client(
            "s3",
            endpoint_url=cfg.r2_endpoint_url,
            aws_access_key_id=cfg.r2_access_key_id,
            aws_secret_access_key=cfg.r2_secret_access_key,
            region_name=cfg.r2_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        ),
        cfg.r2_bucket,
    )


def check() -> int:
    client, bucket = client_and_bucket()
    try:
        current = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except Exception as exc:  # botocore raises NoSuchLifecycleConfiguration
        if "NoSuchLifecycleConfiguration" in str(exc):
            print(f"{bucket}: no lifecycle rules — the retention backstop is NOT in place")
            return 1
        raise

    live = {rule.get("ID"): rule for rule in current.get("Rules", [])}
    expected = {rule["ID"]: rule for rule in RULES["Rules"]}
    problems = []
    for name, rule in expected.items():
        if name not in live:
            problems.append(f"missing rule {name}")
            continue
        if live[name].get("Status") != "Enabled":
            problems.append(f"{name} is not enabled")
        if live[name].get("Expiration", {}).get("Days") != rule["Expiration"]["Days"]:
            problems.append(
                f"{name} expires after {live[name].get('Expiration')}, "
                f"expected {rule['Expiration']}"
            )

    print(json.dumps(current.get("Rules", []), indent=2, default=str))
    for problem in problems:
        print(f"  ! {problem}")
    return 1 if problems else 0


def apply() -> int:
    client, bucket = client_and_bucket()
    client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=RULES)
    print(f"{bucket}: lifecycle rules written")
    return check()


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return apply() if args.apply else check()


if __name__ == "__main__":
    raise SystemExit(main())
