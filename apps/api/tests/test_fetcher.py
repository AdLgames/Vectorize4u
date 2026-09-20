"""§4.3 / §13 — `{url}` input rejects loopback, private, metadata and
redirect-to-private cases."""

from __future__ import annotations

import pytest

from app.fetcher import UnsafeUrl, _is_public, resolve_public_ip, validate

PRIVATE = [
    "127.0.0.1",
    "10.0.0.5",
    "172.16.3.4",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata
    "100.64.0.1",  # CGNAT
    "0.0.0.0",
    "::1",
    "fc00::1",
    "fe80::1",
    "::ffff:127.0.0.1",  # IPv4-mapped loopback
]

PUBLIC = ["1.1.1.1", "8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"]


@pytest.mark.parametrize("address", PRIVATE)
def test_private_addresses_are_rejected(address):
    import ipaddress

    assert _is_public(ipaddress.ip_address(address)) is False


@pytest.mark.parametrize("address", PUBLIC)
def test_public_addresses_are_allowed(address):
    import ipaddress

    assert _is_public(ipaddress.ip_address(address)) is True


def test_http_is_rejected():
    with pytest.raises(UnsafeUrl, match="https"):
        validate("http://example.com/logo.png")


def test_non_443_port_is_rejected():
    with pytest.raises(UnsafeUrl, match="port"):
        validate("https://example.com:8443/logo.png")


def test_localhost_is_rejected():
    with pytest.raises(UnsafeUrl):
        validate("https://localhost/logo.png")


def test_metadata_ip_is_rejected():
    with pytest.raises(UnsafeUrl):
        validate("https://169.254.169.254/latest/meta-data/")


def test_mixed_answers_are_rejected(monkeypatch):
    """A host resolving to both a public and a private address is an attack.

    Checking only the address we intend to use would let it through.
    """
    import socket

    def fake(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(UnsafeUrl, match="non-public"):
        resolve_public_ip("rebind.example.com")


def test_unresolvable_host_is_rejected(monkeypatch):
    import socket

    def fake(*args, **kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(UnsafeUrl, match="cannot resolve"):
        resolve_public_ip("nowhere.invalid")


def test_fetch_follows_at_most_three_redirects(monkeypatch, tmp_env):
    """Every hop is re-validated, and the chain is bounded."""
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )

    import httpx

    from app import fetcher

    class _Response:
        status_code = 302
        headers = {"location": "https://example.com/next"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):  # pragma: no cover - never reached
            yield b""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(httpx, "Client", _Client)
    with pytest.raises(UnsafeUrl, match="redirects"):
        fetcher.fetch("https://example.com/start")


def test_redirect_to_a_private_address_is_rejected(monkeypatch, tmp_env):
    import socket

    import httpx

    from app import fetcher

    def resolve(host, *args, **kwargs):
        address = "127.0.0.1" if host == "internal.example.com" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    class _Response:
        status_code = 302
        headers = {"location": "https://internal.example.com/secrets"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(httpx, "Client", _Client)
    with pytest.raises(UnsafeUrl, match="non-public"):
        fetcher.fetch("https://example.com/start")


def test_api_rejects_unsafe_url(client, auth, user):
    response = client.post("/v1/vectorize", json={"url": "https://127.0.0.1/x.png"}, headers=auth)
    assert response.status_code == 400
    assert response.json()["error_code"] == "unsafe_url"


def test_api_rejects_http_url_at_the_schema(client, auth, user):
    response = client.post("/v1/vectorize", json={"url": "http://example.com/x.png"}, headers=auth)
    assert response.status_code == 422
