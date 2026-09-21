"""Prove a deployed web app is wired to the live API, not to localhost.

`scripts/verify_live.py` proves the API converts an image. This proves the
site people actually visit is pointed at it — a different claim, and the
one with the quieter failure mode. `NEXT_PUBLIC_API_BASE` has a default of
`http://127.0.0.1:8000` (next.config.ts), so a build that never received
the variable deploys perfectly, renders perfectly, ranks perfectly, and
every conversion fails in the browser with a connection error no server
log will ever show. `NEXT_PUBLIC_SITE_URL` has the same shape of default:
miss it and the sitemap advertises vectorize.example to Google.

Neither is visible from the outside except by reading what shipped, which
is what this does:

  * every URL in the sitemap resolves, and is on this origin
  * robots.txt points at that sitemap
  * the JavaScript that shipped names the live API and not localhost
  * the API answers a cross-origin request from this site (§4.3 uploads
    go straight to R2 from the browser, so CORS is load-bearing)

    python scripts/verify_site.py https://vectorize4u.com \\
        --api https://vectorize4u-api.fly.dev

Standard library only, so it runs on a bare CI runner.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

TIMEOUT_S = 30.0

# next.config.ts falls back to these when the environment is missing. Their
# presence in a deployed build is the bug this script exists to catch.
LOCALHOST_MARKERS = ("127.0.0.1:8000", "localhost:8000")
PLACEHOLDER_SITE = "vectorize.example"


class StepFailed(Exception):
    pass


def _get(
    url: str, *, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(url, method="GET")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return (
                response.status,
                response.read(),
                {k.lower(): v for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.read(),
            {k.lower(): v for k, v in (error.headers or {}).items()},
        )
    except urllib.error.URLError as error:
        raise StepFailed(f"GET {url} did not connect: {error.reason}")


def _title(html: str) -> str:
    found = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
    return found.group(1).strip() if found else "(none)"


def _interstitial(html: str, headers: dict[str, str]) -> str | None:
    """Name the wall in front of the site, if there is one.

    A protected Vercel deployment answers *every* path with a sign-in page,
    including /sitemap.xml, and can do it with a 200. Every check below
    then reads that page instead of the site and reports something
    misleading about the app, which is worse than reporting nothing.
    """
    if "_vercel_sso_nonce" in headers.get("set-cookie", ""):
        return "Vercel deployment protection (SSO cookie)"
    for marker in (
        "_vercel/sso",
        "vercel.com/sso",
        "sso-api",
        "Authentication Required",
    ):
        if marker in html:
            return f"Vercel deployment protection ({marker})"
    if "Password Protection" in html or "password-protection" in html:
        return "Vercel password protection"
    return None


def home(site: str) -> str:
    status, raw, headers = _get(site + "/")
    if status != 200:
        raise StepFailed(f"GET / answered {status}")
    html = raw.decode("utf-8", "replace")
    if "<title" not in html:
        raise StepFailed("the home page has no <title>, so it is not the app")

    wall = _interstitial(html, headers)
    if wall:
        raise StepFailed(
            f"this URL is behind {wall}, so nothing here is the app — the page "
            f"titled {_title(html)!r} is served for every path, /sitemap.xml "
            "included.\n"
            "      Either check the *production* URL (Vercel's Domains page "
            "lists it; protection normally covers previews only), or turn the "
            "protection off under Settings -> Deployment Protection."
        )
    print(f"  home        ok  ({len(raw)} bytes, title {_title(html)!r})")
    return html


def sitemap(site: str) -> list[str]:
    status, raw, headers = _get(site + "/sitemap.xml")
    if status != 200:
        raise StepFailed(f"GET /sitemap.xml answered {status}")
    body = raw.decode("utf-8", "replace")
    locations = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    if not locations:
        wall = _interstitial(body, headers)
        raise StepFailed(
            "the sitemap lists no URLs. "
            + (
                f"It is {wall}, not a sitemap."
                if wall
                else f"content-type {headers.get('content-type', '(none)')!r}, "
                f"{len(raw)} bytes, starting: {body[:180]!r}"
            )
        )

    if any(PLACEHOLDER_SITE in url for url in locations):
        raise StepFailed(
            f"the sitemap advertises {PLACEHOLDER_SITE}, so the build never received "
            "NEXT_PUBLIC_SITE_URL. Every canonical and every indexed URL is wrong."
        )
    wrong_origin = [url for url in locations if not url.startswith(site)]
    if wrong_origin:
        raise StepFailed(
            f"the sitemap points somewhere else, e.g. {wrong_origin[0]} — "
            f"NEXT_PUBLIC_SITE_URL does not match {site}"
        )
    # sitemap.ts builds `${SITE}/path`, so a NEXT_PUBLIC_SITE_URL that ends
    # in a slash yields `https://host//path`. It still resolves, which is
    # why it survives a look at the site, and every canonical is wrong.
    doubled = [url for url in locations if "//" in url.split("://", 1)[-1]]
    if doubled:
        raise StepFailed(
            f"the sitemap has a doubled slash, e.g. {doubled[0]} — "
            "NEXT_PUBLIC_SITE_URL ends in a '/' and must not"
        )
    print(f"  sitemap     ok  ({len(locations)} URLs)")
    return locations


def pages_resolve(site: str, locations: list[str]) -> None:
    """A sitemap that lists a 404 is worse than no sitemap."""
    broken = []
    for url in locations:
        status, _, _ = _get(url)
        if status != 200:
            broken.append(f"{urlparse(url).path or '/'} -> {status}")
    if broken:
        raise StepFailed(
            "the sitemap lists URLs that do not resolve: " + ", ".join(broken)
        )
    print(f"  pages       ok  (all {len(locations)} resolve)")


def api_base_is_baked_in(site: str, html: str, api: str) -> None:
    """Read what shipped, not what the deploy was asked to ship.

    Next inlines these at build time, so the only honest check is to fetch
    the bundles the page loads and look. The home page pulls the converter,
    which is the code that calls the API.
    """
    host = urlparse(api).netloc
    haystacks = [html]
    scripts = re.findall(r'src="(/_next/static/[^"]+\.js)"', html)
    for path in scripts[:20]:
        status, raw, _ = _get(site + path)
        if status == 200:
            haystacks.append(raw.decode("utf-8", "replace"))

    combined = "\n".join(haystacks)
    for marker in LOCALHOST_MARKERS:
        if marker in combined:
            raise StepFailed(
                f"the deployed JavaScript still points at {marker}. The build did not "
                "receive NEXT_PUBLIC_API_BASE, so the site renders but cannot convert."
            )
    if host not in combined:
        raise StepFailed(
            f"{host} appears nowhere in the home page or its {len(scripts)} scripts, so "
            "this build is not talking to the API this check was given"
        )
    print(f"  api base    ok  ({host}, in {len(haystacks) - 1} bundles)")


def api_accepts_this_origin(site: str, api: str) -> None:
    """§4.3 puts the browser in direct contact with the API and with R2."""
    status, _, headers = _get(f"{api}/health", headers={"Origin": site})
    if status != 200:
        raise StepFailed(f"the API answered {status} for /health with an Origin header")
    allowed = headers.get("access-control-allow-origin")
    if not allowed:
        raise StepFailed(
            f"the API sent no Access-Control-Allow-Origin for {site}, so every call "
            "the browser makes will be blocked"
        )
    if allowed not in ("*", site):
        raise StepFailed(f"the API allows {allowed!r}, which is not {site}")
    print(f"  cors        ok  (allow-origin: {allowed})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_url", help="e.g. https://vectorize4u.com")
    parser.add_argument(
        "--api", required=True, help="e.g. https://vectorize4u-api.fly.dev"
    )
    args = parser.parse_args()

    site = args.site_url.rstrip("/")
    api = args.api.rstrip("/")
    print(f"verifying {site} against {api}")

    try:
        html = home(site)
        locations = sitemap(site)
        pages_resolve(site, locations)
        api_base_is_baked_in(site, html, api)
        api_accepts_this_origin(site, api)

        status, raw, _ = _get(site + "/robots.txt")
        if status != 200:
            raise StepFailed(f"GET /robots.txt answered {status}")
        if "sitemap" not in raw.decode("utf-8", "replace").lower():
            raise StepFailed("robots.txt does not point at the sitemap")
        print("  robots      ok")
    except StepFailed as failure:
        print(f"\nFAILED: {failure}", file=sys.stderr)
        return 1

    print("\nthe deployed site is wired to the live API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
