"""§4.3 — fetching `{url}` input without becoming an SSRF gadget.

The rules, all of which matter:

- `https` only.
- Resolve DNS first, reject non-public addresses, and then **connect to the
  resolved IP**, so a second DNS answer cannot rebind us onto an internal
  host between the check and the connection.
- No redirects unless every hop is re-validated, max 3.
- Stream with a 25 MB cap and a 10 s total timeout.
- Run from a process with no route to internal services (deployment
  concern; this module is the half that can be enforced in code).
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx

from app.config import settings

MAX_REDIRECTS = 3
TOTAL_TIMEOUT_S = 10.0


class UnsafeUrl(Exception):
    """The URL is not fetchable. Always a 400: the caller supplied it."""


@dataclass(frozen=True)
class Fetched:
    data: bytes
    content_type: str
    final_url: str


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject loopback, private, link-local, CGNAT and metadata ranges, v4 and v6."""
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
        return False
    if ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        # 100.64.0.0/10 — carrier-grade NAT. `is_private` does not cover it
        # on every Python version, and cloud providers do route it.
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return False
        # 169.254.169.254 is link-local and already rejected; named here so
        # the intent survives a future refactor of the checks above.
        if str(ip) == "169.254.169.254":
            return False
    else:
        # IPv4-mapped IPv6 (::ffff:127.0.0.1) must be judged as its v4 form.
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            return _is_public(mapped)
        if ip in ipaddress.ip_network("fc00::/7"):  # unique local
            return False
        if ip in ipaddress.ip_network("fe80::/10"):  # link-local
            return False
    return True


def resolve_public_ip(host: str) -> str:
    """Resolve `host` and return one address, or raise if any answer is internal.

    Every answer is checked, not just the one we use: a host that resolves to
    both a public and a private address is an attack, not a coincidence.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"cannot resolve {host}") from exc

    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        raise UnsafeUrl(f"cannot resolve {host}")

    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])
        except ValueError as exc:
            raise UnsafeUrl(f"bad address for {host}: {raw}") from exc
        if not _is_public(ip):
            raise UnsafeUrl(f"{host} resolves to a non-public address ({ip})")

    return sorted(addresses)[0]


def validate(url: str) -> tuple[str, str]:
    """Return (resolved_ip, host) or raise UnsafeUrl."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeUrl("only https URLs are accepted")
    if not parsed.hostname:
        raise UnsafeUrl("missing host")
    if parsed.port is not None and parsed.port not in (443,):
        raise UnsafeUrl("only port 443 is accepted")
    return resolve_public_ip(parsed.hostname), parsed.hostname


def fetch(url: str, *, max_bytes: int | None = None) -> Fetched:
    """Fetch `url` safely. Raises UnsafeUrl for anything that fails the rules."""
    max_bytes = max_bytes or settings().max_upload_bytes
    deadline = time.monotonic() + TOTAL_TIMEOUT_S
    current = url

    for _ in range(MAX_REDIRECTS + 1):
        if time.monotonic() > deadline:
            raise UnsafeUrl("timed out")

        ip, host = validate(current)
        parsed = urlparse(current)
        # Connect to the address we checked, not to whatever DNS says next.
        connect_host = f"[{ip}]" if ":" in ip else ip
        target = urlunparse(parsed._replace(netloc=connect_host))

        remaining = max(0.5, deadline - time.monotonic())
        with httpx.Client(
            timeout=httpx.Timeout(remaining),
            follow_redirects=False,
            verify=True,
            headers={"Host": host, "User-Agent": "vectorize-fetcher/1"},
        ) as client, client.stream("GET", target, extensions={"sni_hostname": host}) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise UnsafeUrl("redirect without a location")
                current = httpx.URL(current).join(location).__str__()
                continue
            if response.status_code >= 400:
                raise UnsafeUrl(f"upstream returned {response.status_code}")

            declared = response.headers.get("content-length")
            if declared and int(declared) > max_bytes:
                raise UnsafeUrl(f"content-length {declared} exceeds {max_bytes}")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise UnsafeUrl(f"body exceeds {max_bytes} bytes")
                if time.monotonic() > deadline:
                    raise UnsafeUrl("timed out")
                chunks.append(chunk)

            return Fetched(
                data=b"".join(chunks),
                content_type=response.headers.get("content-type", ""),
                final_url=current,
            )

    raise UnsafeUrl(f"more than {MAX_REDIRECTS} redirects")
