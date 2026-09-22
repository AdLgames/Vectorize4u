"""§6 / §13 — the request path, end to end, with the engine really running."""

from __future__ import annotations

import pytest

from app import credits
from tests.conftest import upload_and_vectorize


@pytest.fixture()
def funded(session, user):
    credits.grant(session, user.id, source="pack", amount=10)
    session.commit()
    return user


def test_upload_vectorize_unlock_download(client, auth, funded, logo_png):
    response = upload_and_vectorize(client, auth, logo_png, {"format": ["svg", "dxf"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["classification"] == "LOGO_FLAT"
    assert body["quality"]["fidelity"] > 0.9
    assert body["quality"]["score_version"]

    # §13: no route returns SVG or any vector output for a locked job.
    assert body["outputs"] == {}
    assert body["unlocked"] is False

    unlocked = client.post(f"/v1/jobs/{body['id']}/unlock", headers=auth)
    assert unlocked.status_code == 200, unlocked.text
    unlocked_body = unlocked.json()
    assert unlocked_body["unlocked"] is True
    assert unlocked_body["credits_charged"] == 1
    assert set(unlocked_body["outputs"]) == {"svg", "dxf"}

    svg = client.get(unlocked_body["outputs"]["svg"])
    assert svg.status_code == 200
    assert svg.content.startswith(b"<svg")

    dxf = client.get(unlocked_body["outputs"]["dxf"])
    assert dxf.status_code == 200
    assert b"$INSUNITS" in dxf.content


def test_locked_job_never_exposes_vector_output(client, auth, funded, logo_png):
    response = upload_and_vectorize(client, auth, logo_png, {"format": ["svg", "dxf", "png"]})
    body = response.json()
    fetched = client.get(f"/v1/jobs/{body['id']}", headers=auth).json()
    for fmt in ("svg", "dxf", "pdf", "eps"):
        assert fmt not in fetched["outputs"], f"{fmt} leaked before unlock"


def test_preview_tiles_are_raster_and_watermarked(client, auth, funded, logo_png):
    body = upload_and_vectorize(client, auth, logo_png).json()
    tile = client.get(f"/v1/jobs/{body['id']}/preview?w=128&h=128&scale=1", headers=auth)
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/png"
    assert tile.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Private and short-lived: user artwork never enters a shared cache (§8).
    assert "private" in tile.headers["cache-control"]


def test_tile_scale_is_capped_at_eight(client, auth, funded, logo_png):
    body = upload_and_vectorize(client, auth, logo_png).json()
    huge = client.get(f"/v1/jobs/{body['id']}/preview?scale=100&w=64&h=64", headers=auth)
    assert huge.status_code == 200


def test_idempotency_creates_one_job_and_one_charge(client, auth, funded, logo_png):
    created = client.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": len(logo_png)},
        headers=auth,
    ).json()
    client.put(created["put_url"], content=logo_png, headers={"Content-Type": "image/png"})

    headers = {**auth, "Idempotency-Key": "key-123"}
    payload = {"upload_id": created["upload_id"], "options": {}}
    first = client.post("/v1/vectorize", json=payload, headers=headers)
    second = client.post("/v1/vectorize", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    from app.db import session_factory
    from app.models import Job

    with session_factory()() as s:
        assert s.query(Job).count() == 1


def test_idempotency_key_reuse_with_different_body_is_a_conflict(
    client, auth, funded, logo_png
):
    def slot():
        created = client.post(
            "/v1/uploads",
            json={"content_type": "image/png", "content_length": len(logo_png)},
            headers=auth,
        ).json()
        client.put(created["put_url"], content=logo_png, headers={"Content-Type": "image/png"})
        return created["upload_id"]

    headers = {**auth, "Idempotency-Key": "key-456"}
    client.post("/v1/vectorize", json={"upload_id": slot(), "options": {}}, headers=headers)
    clash = client.post(
        "/v1/vectorize", json={"upload_id": slot(), "options": {}}, headers=headers
    )
    assert clash.status_code == 409
    assert clash.json()["error_code"] == "idempotency_key_reused"


def test_respond_async_returns_202_immediately(client, auth, funded, logo_png):
    created = client.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": len(logo_png)},
        headers=auth,
    ).json()
    client.put(created["put_url"], content=logo_png, headers={"Content-Type": "image/png"})
    response = client.post(
        "/v1/vectorize",
        json={"upload_id": created["upload_id"], "options": {}},
        headers={**auth, "Prefer": "respond-async"},
    )
    assert response.status_code == 202


def test_second_unlock_of_the_same_image_is_free(client, auth, funded, logo_png):
    """One charge per source image; every revision shares a root_job_id."""
    body = upload_and_vectorize(client, auth, logo_png).json()
    client.post(f"/v1/jobs/{body['id']}/unlock", headers=auth)

    tweak = client.post(
        f"/v1/jobs/{body['id']}/tweak",
        json={"options": {"max_colors": 4}},
        headers=auth,
    )
    assert tweak.status_code == 200, tweak.text
    child = tweak.json()

    unlocked = client.post(f"/v1/jobs/{child['id']}/unlock", headers=auth).json()
    assert unlocked["unlocked"] is True
    assert unlocked["credits_charged"] == 0

    account = client.get("/v1/account", headers=auth).json()
    assert account["credits"] == 9, "the tweak was charged a second time"


def test_out_of_credits_is_402(client, auth, user, logo_png):
    body = upload_and_vectorize(client, auth, logo_png).json()
    response = client.post(f"/v1/jobs/{body['id']}/unlock", headers=auth)
    assert response.status_code == 402
    problem = response.json()
    assert problem["error_code"] == "insufficient_credits"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_anonymous_preview_needs_no_account(client, logo_png):
    created = client.post(
        "/v1/uploads", json={"content_type": "image/png", "content_length": len(logo_png)}
    ).json()
    client.put(created["put_url"], content=logo_png, headers={"Content-Type": "image/png"})
    response = client.post("/v1/preview", json={"upload_id": created["upload_id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["outputs"] == {}
    assert "X-Preview-Remaining" in response.headers


def test_preview_rate_limit(client, logo_png, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "preview_limit_anonymous_per_hour", 2)
    codes = []
    for _ in range(3):
        created = client.post(
            "/v1/uploads",
            json={"content_type": "image/png", "content_length": len(logo_png)},
        ).json()
        client.put(created["put_url"], content=logo_png, headers={"Content-Type": "image/png"})
        codes.append(
            client.post("/v1/preview", json={"upload_id": created["upload_id"]}).status_code
        )
    assert codes[-1] == 429


def test_delete_purges_immediately(client, auth, funded, logo_png):
    body = upload_and_vectorize(client, auth, logo_png).json()
    unlocked = client.post(f"/v1/jobs/{body['id']}/unlock", headers=auth).json()
    url = unlocked["outputs"]["svg"]
    assert client.get(url).status_code == 200

    assert client.delete(f"/v1/jobs/{body['id']}", headers=auth).status_code == 204
    # Deleted jobs are unreachable immediately (§13).
    assert client.get(url).status_code == 404

    from app.db import session_factory
    from app.models import Job

    with session_factory()() as s:
        job = s.get(Job, body["id"])
        # The statistical rows survive; the attribution does not (§5).
        assert job.profile is not None
        assert job.user_id is None
        assert job.source_key is None


def test_failed_job_is_never_billed(client, auth, funded):
    created = client.post(
        "/v1/uploads", json={"content_type": "image/png", "content_length": 12}, headers=auth
    ).json()
    client.put(created["put_url"], content=b"not an image", headers={"Content-Type": "image/png"})
    response = client.post(
        "/v1/vectorize", json={"upload_id": created["upload_id"]}, headers=auth
    )
    body = response.json()
    assert body["status"] == "failed"
    assert body["credits_charged"] == 0
    assert body["error_code"] in ("unsupported_format", "bad_image")

    unlock = client.post(f"/v1/jobs/{body['id']}/unlock", headers=auth)
    assert unlock.status_code == 409

    account = client.get("/v1/account", headers=auth).json()
    assert account["credits"] == 10


def test_upload_rejects_oversize_declaration(client, auth):
    response = client.post(
        "/v1/uploads",
        json={"content_type": "image/png", "content_length": 99 * 1024 * 1024},
        headers=auth,
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == "image_too_large"


def test_upload_rejects_non_image_content_type(client, auth):
    response = client.post(
        "/v1/uploads",
        json={"content_type": "application/zip", "content_length": 100},
        headers=auth,
    )
    assert response.status_code == 415


def test_another_users_job_is_not_found(client, auth, funded, logo_png, session):
    from app.models import User
    from tests.conftest import session_token

    body = upload_and_vectorize(client, auth, logo_png).json()

    session.add(User(id="usr_other", email="other@example.com"))
    session.commit()
    other = {
        "Authorization": f"Bearer {session_token('usr_other', 'other@example.com')}"
    }
    assert client.get(f"/v1/jobs/{body['id']}", headers=other).status_code == 404


def test_api_key_job_is_charged_on_completion(client, auth, funded, logo_png):
    """API jobs are debited on successful completion, web jobs at unlock."""
    key = client.post("/v1/account/keys", json={"label": "ci"}, headers=auth).json()
    api_headers = {"Authorization": f"Bearer {key['key']}"}

    response = upload_and_vectorize(client, api_headers, logo_png)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "complete"
    assert body["credits_charged"] == 1
    # API callers get their output without an unlock step.
    assert "svg" in body["outputs"]

    account = client.get("/v1/account", headers=auth).json()
    assert account["credits"] == 9


def test_api_key_is_shown_once(client, auth, user):
    created = client.post("/v1/account/keys", json={"label": "one"}, headers=auth).json()
    assert created["key"].startswith("v4u_live_")
    listed = client.get("/v1/account/keys", headers=auth).json()
    assert listed[0]["key"] is None


def test_revoked_key_is_rejected(client, auth, user, logo_png):
    created = client.post("/v1/account/keys", json={}, headers=auth).json()
    client.delete(f"/v1/account/keys/{created['id']}", headers=auth)
    response = client.get(
        "/v1/account", headers={"Authorization": f"Bearer {created['key']}"}
    )
    assert response.status_code == 401


def test_smoothing_is_accepted_and_reaches_the_engine(client, auth, funded, logo_png):
    """The trade this option makes is deliberate: it rounds off the pixel
    staircase in the traced outline, so the result is smoother artwork and
    a *lower* score against the aliased source. Both halves are the point,
    so both are asserted — against an explicit 0, not against the default,
    which now chooses a level itself."""
    off = upload_and_vectorize(client, auth, logo_png, {"format": ["svg"], "smoothing": 0})
    smoothed = upload_and_vectorize(
        client, auth, logo_png, {"format": ["svg"], "smoothing": 8}
    )
    assert off.status_code == 200, off.text
    assert smoothed.status_code == 200, smoothed.text
    assert smoothed.json()["quality"]["nodes"] <= off.json()["quality"]["nodes"]


def test_smoothing_defaults_to_the_engine_choosing(client, auth, funded, logo_png):
    """Omitting the option is not the same as sending 0.

    The customer who most needs smoothing is the one who does not know the
    option exists — a low-resolution logo comes back stepped and "there is
    a slider for that" is not an answer they ever reach. So the default
    decides, and 0 remains available to mean off.
    """
    response = upload_and_vectorize(client, auth, logo_png, {"format": ["svg"]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "complete"


def test_smoothing_is_bounded(client, auth, funded, logo_png):
    """An unbounded blur radius is a denial-of-service knob: the kernel is
    derived from it and the cost is quadratic."""
    response = upload_and_vectorize(
        client, auth, logo_png, {"format": ["svg"], "smoothing": 99}
    )
    assert response.status_code == 422
