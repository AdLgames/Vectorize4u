"""Job and batch callbacks (§6).

`webhook_url` used to be accepted on a job and silently dropped — the field
validated, the job ran, and nothing was ever delivered. These tests are what
stops that being true again.
"""

from __future__ import annotations

import pytest

from tests.conftest import upload_and_vectorize


@pytest.fixture()
def delivered(monkeypatch):
    """Capture callbacks instead of making them."""
    from worker import tasks

    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        tasks, "deliver_webhook_inline", lambda url, payload: sent.append((url, payload))
    )
    return sent


def _vectorize(client, headers, data, **body_extra):
    created = client.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": len(data)},
        headers=headers,
    ).json()
    client.put(created["put_url"], content=data, headers={"Content-Type": "image/png"})
    body = {"upload_id": created["upload_id"], **body_extra}
    return client.post("/v1/vectorize", json=body, headers=headers)


def test_a_finished_job_calls_back(client, auth, logo_png, delivered):
    response = _vectorize(client, auth, logo_png, webhook_url="https://example.com/hook")
    assert response.status_code == 200

    assert len(delivered) == 1
    url, payload = delivered[0]
    assert url == "https://example.com/hook"
    assert payload["type"] == "job.complete"
    assert payload["job_id"] == response.json()["id"]
    assert payload["status"] == "complete"


def test_a_failed_job_calls_back_too(client, auth, delivered):
    """Silence on failure is the worst case: the caller polls forever."""
    response = _vectorize(client, auth, b"not an image", webhook_url="https://example.com/hook")
    assert response.json()["status"] == "failed"

    assert [p["type"] for _, p in delivered] == ["job.failed"]
    assert delivered[0][1]["error_code"]


def test_a_job_without_a_callback_makes_no_call(client, auth, logo_png, delivered):
    assert upload_and_vectorize(client, auth, logo_png).status_code == 200
    assert delivered == []


def test_previews_never_call_back(client, logo_png, delivered):
    """`/v1/preview` is anonymous and free. Honouring a callback there would
    make it a way to have us POST to any host on demand."""
    created = client.post(
        "/v1/uploads", json={"content_type": "image/png", "content_length": len(logo_png)}
    ).json()
    client.put(created["put_url"], content=logo_png, headers={"Content-Type": "image/png"})
    response = client.post(
        "/v1/preview",
        json={"upload_id": created["upload_id"], "webhook_url": "https://example.com/hook"},
    )
    assert response.status_code == 200
    assert delivered == []


def test_a_plain_http_callback_is_refused_at_the_edge(client, auth, logo_png):
    created = client.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": len(logo_png)},
        headers=auth,
    ).json()
    response = client.post(
        "/v1/vectorize",
        json={"upload_id": created["upload_id"], "webhook_url": "http://example.com/hook"},
        headers=auth,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://localhost/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/hook",
    ],
)
def test_delivery_refuses_an_internal_destination(url):
    """Checked again at delivery, not only when the job was accepted: DNS
    can change in between, and that is exactly the attack."""
    from worker.tasks import deliver_webhook_inline

    result = deliver_webhook_inline(url, {"type": "job.complete"})
    assert result["status"] == "refused"


def test_the_signature_covers_timestamp_and_body(monkeypatch):
    """Exercised through a real httpx client with a mock transport.

    The previous version of this test replaced `httpx.post` with a stub
    that accepted anything, and so it happily passed while the real call
    raised `TypeError: post() got an unexpected keyword argument
    'extensions'` — every delivery failing, and failing in the shape of a
    customer endpoint being down. Swap the transport, not the call.
    """
    import hashlib
    import hmac
    import json

    import httpx
    from worker import tasks

    from app.config import settings

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["content"] = request.content
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200)

    monkeypatch.setattr(tasks, "_resolve_callback", lambda url: ("93.184.216.34", "example.com"))
    monkeypatch.setattr(
        tasks,
        "_webhook_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )

    payload = {"type": "job.complete", "job_id": "job_1"}
    result = tasks.deliver_webhook_inline("https://example.com/hook", payload)
    assert result["status"] == "delivered"

    # Connected to the address we checked, with the real host in the
    # header and the real hostname offered for TLS.
    assert seen["url"] == "https://93.184.216.34/hook"
    assert seen["headers"]["Host"] == "example.com"
    assert seen["sni"] == "example.com"

    timestamp = seen["headers"]["X-Vectorize-Timestamp"]
    expected = hmac.new(
        settings().webhook_signing_secret.encode(),
        timestamp.encode() + b"." + seen["content"],
        hashlib.sha256,
    ).hexdigest()
    assert seen["headers"]["X-Vectorize-Signature"] == f"sha256={expected}"
    assert json.loads(seen["content"]) == payload


def test_a_delivery_that_raises_is_retried_not_swallowed():
    """The bug this file now guards: a TypeError in our own code came back
    as a delivery failure, which is retried forever and looks like the
    customer's fault."""
    import httpx
    from worker import tasks
    from worker.tasks import WebhookDeliveryFailed

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    original = tasks._webhook_client
    tasks._webhook_client = lambda: httpx.Client(transport=httpx.MockTransport(explode))
    tasks._resolve_callback = lambda url: ("93.184.216.34", "example.com")
    try:
        with pytest.raises(WebhookDeliveryFailed):
            tasks.deliver_webhook_inline("https://example.com/hook", {"type": "job.complete"})
    finally:
        tasks._webhook_client = original
