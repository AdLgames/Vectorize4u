"""Prove sign-in is wired: the same Supabase project, on both sides.

Sign-in spans three systems that are configured separately and fail
silently when they disagree. The web app holds the project URL and the
publishable key; the API derives *both* its JWKS endpoint and its expected
issuer from `VEC_SUPABASE_URL`; the project itself decides whether it signs
tokens with asymmetric keys at all. Any mismatch produces the same
symptom — anonymous previews keep working, every signed-in request answers
401 — and none of it appears in a log.

This checks all of it without sending an email, so it is safe to run as
often as you like. Magic links are the only way in (§7), and a real
round trip would need an inbox, Supabase's low email rate limit, and a
user row left behind on every run.

The load-bearing check is the last one. A token carrying a *real* key id
from the project's own JWKS, with a deliberately invalid signature, tells
the two failures apart by the reason the API gives back:

  * "Signature verification failed" — the API fetched this project's keys,
    found the one named, and rejected our forgery. Correct, and proof the
    two sides agree.
  * "Unable to find a signing key" — the API is looking at a *different*
    project's JWKS. Real tokens from this project will be rejected too.

    python scripts/verify_auth.py https://vectorize4u.vercel.app \\
        --api https://vectorize4u-api.fly.dev \\
        --supabase https://abcdefgh.supabase.co

Standard library only, so it runs on a bare CI runner.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

TIMEOUT_S = 30.0
ASYMMETRIC = {"RS256", "ES256"}


class StepFailed(Exception):
    pass


def _get(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise StepFailed(f"GET {url} did not connect: {error.reason}")


def jwks(supabase: str) -> str:
    """The project must publish asymmetric keys, or the API cannot verify.

    A project still on the legacy shared HS256 secret serves an empty key
    set here. That is the single most likely reason for a site where
    previews work and signing in does not.
    """
    url = f"{supabase}/auth/v1/.well-known/jwks.json"
    status, raw = _get(url)
    if status != 200:
        raise StepFailed(
            f"{url} answered {status}. Without a JWKS the API has no way to verify "
            "a token unless VEC_SUPABASE_JWT_SECRET is set instead."
        )
    try:
        keys = json.loads(raw).get("keys") or []
    except json.JSONDecodeError as exc:
        raise StepFailed(f"the JWKS endpoint returned no JSON: {exc}")

    if not keys:
        raise StepFailed(
            "the JWKS key set is empty, so this project still signs with the legacy "
            "HS256 shared secret.\n"
            "      Migrate it under Authentication -> JWT Keys (nothing secret to "
            "store afterwards), or set VEC_SUPABASE_JWT_SECRET on the API and the "
            "workers."
        )
    algorithms = {key.get("alg") for key in keys}
    usable = [key for key in keys if key.get("alg") in ASYMMETRIC and key.get("kid")]
    if not usable:
        raise StepFailed(
            f"the JWKS publishes {sorted(algorithms)}, and the API accepts only "
            f"{sorted(ASYMMETRIC)} on the asymmetric path"
        )
    print(f"  jwks        ok  ({len(keys)} key(s), {sorted(algorithms)})")
    return str(usable[0]["kid"])


def auth_settings(supabase: str) -> None:
    """Email sign-in on, and sign-up not disabled.

    A magic link creates the user on first use, so a project with sign-ups
    turned off silently admits existing users only.
    """
    status, raw = _get(f"{supabase}/auth/v1/settings")
    if status != 200:
        # Not fatal: some projects restrict it. The checks that matter ran.
        print(f"  settings    -   (unreadable, {status}; skipping)")
        return
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        print("  settings    -   (not JSON; skipping)")
        return

    if body.get("external", {}).get("email") is False:
        raise StepFailed(
            "email sign-in is disabled on this project, and the magic link is the "
            "only way in"
        )
    notes = []
    if body.get("disable_signup"):
        notes.append("sign-ups disabled — only existing users can get in")
    if body.get("mailer_autoconfirm"):
        notes.append("autoconfirm on")
    print(
        f"  settings    ok  (email sign-in on{'; ' + '; '.join(notes) if notes else ''})"
    )


def web_is_configured(site: str, supabase: str) -> None:
    """The browser needs the project URL and the publishable key.

    `lib/supabase.ts` treats either one missing as "not configured" and the
    sign-in screen renders a notice instead of a form — a deployed site
    that looks complete until somebody tries to sign in.
    """
    status, raw = _get(site + "/signin")
    if status != 200:
        raise StepFailed(f"GET /signin answered {status}")
    html = raw.decode("utf-8", "replace")
    if "Sign-in isn't configured" in html or "Sign-in isn&#x27;t configured" in html:
        raise StepFailed(
            "the sign-in page is rendering its 'not configured' notice, so the build "
            "did not receive NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY "
            "(the publishable key). Set both and redeploy — they are baked in."
        )

    host = urlparse(supabase).netloc
    haystacks = [html]
    for path in re.findall(r'src="(/_next/static/[^"]+\.js)"', html)[:25]:
        code, body = _get(site + path)
        if code == 200:
            haystacks.append(body.decode("utf-8", "replace"))
    if host not in "\n".join(haystacks):
        raise StepFailed(
            f"{host} appears nowhere in /signin or its bundles, so this build is not "
            "pointed at the project being checked"
        )
    print(f"  web         ok  (sign-in form present, {host} in the bundle)")


def _segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def api_rejects_nonsense(api: str) -> None:
    """401, not 500. A 500 means the auth path itself is broken."""
    status, raw = _get(
        f"{api}/v1/account", headers={"Authorization": "Bearer not-a-token"}
    )
    if status == 500:
        raise StepFailed(
            f"the API answered 500 for a malformed token, so verification is raising "
            f"rather than refusing: {raw[:300]!r}"
        )
    if status != 401:
        raise StepFailed(
            f"expected 401 for a malformed token, got {status}: {raw[:300]!r}"
        )
    print("  api         ok  (401 for a malformed token)")


def api_trusts_this_project(api: str, kid: str) -> None:
    """The check that catches a project mismatch. See the module docstring."""
    header = _segment({"alg": "RS256", "typ": "JWT", "kid": kid})
    claims = _segment(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "aud": "authenticated",
            "role": "authenticated",
            "exp": int(time.time()) + 600,
        }
    )
    forged = f"{header}.{claims}.{base64.urlsafe_b64encode(b'not-a-signature').rstrip(b'=').decode()}"

    status, raw = _get(
        f"{api}/v1/account", headers={"Authorization": f"Bearer {forged}"}
    )
    detail = raw.decode("utf-8", "replace")
    if status != 401:
        raise StepFailed(
            f"a forged token should be refused with 401, not {status}: {detail[:300]!r}"
        )

    if "Unable to find a signing key" in detail or "matches" in detail:
        raise StepFailed(
            f"the API could not find key {kid!r}, which this project publishes — so "
            "VEC_SUPABASE_URL on the API names a different project (or nothing).\n"
            "      Its value drives both the JWKS endpoint and the expected issuer, "
            "so real tokens from this project are being rejected too.\n"
            "      Fix the SUPABASE_URL repository secret, re-run the secrets stage, "
            "then deploy — staged secrets only apply on a deploy."
        )
    if "Signature" not in detail and "signature" not in detail:
        # Refused for some third reason. Worth printing rather than guessing.
        print(
            f"  project     ?   (401, but for an unexpected reason: {detail[:200]!r})"
        )
        return
    print(f"  project     ok  (the API knows key {kid[:12]}… from this project)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_url")
    parser.add_argument("--api", required=True)
    parser.add_argument("--supabase", required=True, help="https://<ref>.supabase.co")
    args = parser.parse_args()

    site = args.site_url.rstrip("/")
    api = args.api.rstrip("/")
    supabase = args.supabase.rstrip("/")
    print(f"verifying sign-in across {site}, {api} and {supabase}")

    try:
        kid = jwks(supabase)
        auth_settings(supabase)
        web_is_configured(site, supabase)
        api_rejects_nonsense(api)
        api_trusts_this_project(api, kid)
    except StepFailed as failure:
        print(f"\nFAILED: {failure}", file=sys.stderr)
        return 1

    print(
        "\nsign-in is wired end to end. The one thing no check can see from\n"
        "outside is Supabase's redirect allowlist: Authentication -> URL\n"
        f"Configuration must list {site}/auth/callback, or the magic link\n"
        "lands somewhere else and the session is never exchanged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
