"""Supabase session verification.

These forge tokens the exact shape Supabase issues, because the interesting
cases are all the ones that must be *rejected* — and you cannot ask a real
Supabase project for an expired token, a token signed with the wrong key,
or a token whose algorithm header has been swapped.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest

from app.config import settings
from app.models import User, utcnow

PROJECT = "https://abcdefghijklmno.supabase.co"
SECRET = "a-legacy-supabase-jwt-secret-that-is-long-enough"


def supabase_token(
    *,
    secret: str = SECRET,
    sub: str | None = None,
    email: str = "buyer@example.com",
    aud: str = "authenticated",
    iss: str | None = None,
    expires_in: int = 3600,
    algorithm: str = "HS256",
    verified: bool = True,
    extra: dict | None = None,
) -> str:
    now = utcnow()
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "email": email,
        "aud": aud,
        "role": "authenticated",
        "iss": iss if iss is not None else f"{PROJECT}/auth/v1",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "user_metadata": {"email_verified": verified},
    }
    claims.update(extra or {})
    return jwt.encode(claims, secret, algorithm=algorithm)


@pytest.fixture()
def legacy_project(tmp_env, monkeypatch):
    """A Supabase project on the legacy shared-secret signing scheme."""
    cfg = settings()
    monkeypatch.setattr(cfg, "supabase_url", PROJECT)
    monkeypatch.setattr(cfg, "supabase_jwt_secret", SECRET)
    return cfg


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_valid_session_creates_the_account(client, legacy_project):
    response = client.get("/v1/account", headers=_auth(supabase_token()))
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "buyer@example.com"


def test_the_supabase_uuid_is_the_account_key(client, legacy_project):
    subject = str(uuid.uuid4())
    first = client.get("/v1/account", headers=_auth(supabase_token(sub=subject))).json()
    second = client.get("/v1/account", headers=_auth(supabase_token(sub=subject))).json()
    assert first["user_id"] == second["user_id"] == subject


def test_a_changed_email_follows_the_account(client, legacy_project):
    subject = str(uuid.uuid4())
    client.get("/v1/account", headers=_auth(supabase_token(sub=subject, email="old@example.com")))
    updated = client.get(
        "/v1/account", headers=_auth(supabase_token(sub=subject, email="new@example.com"))
    ).json()
    assert updated["user_id"] == subject
    assert updated["email"] == "new@example.com"


def test_a_wrong_signature_is_rejected(client, legacy_project):
    forged = supabase_token(secret="not-the-projects-secret")
    assert client.get("/v1/account", headers=_auth(forged)).status_code == 401


def test_an_expired_session_is_rejected(client, legacy_project):
    stale = supabase_token(expires_in=-60)
    assert client.get("/v1/account", headers=_auth(stale)).status_code == 401


def test_the_wrong_audience_is_rejected(client, legacy_project):
    """Supabase issues service tokens too; only session tokens may sign in."""
    other = supabase_token(aud="service_role")
    assert client.get("/v1/account", headers=_auth(other)).status_code == 401


def test_a_token_from_another_project_is_rejected(client, legacy_project):
    other = supabase_token(iss="https://someone-elses.supabase.co/auth/v1")
    assert client.get("/v1/account", headers=_auth(other)).status_code == 401


def test_alg_none_is_rejected(client, legacy_project):
    """The classic downgrade: strip the signature and claim it was intended.

    Rejected because the algorithm list is fixed at the call site rather
    than read from the token's own header.
    """
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "attacker@example.com",
            "aud": "authenticated",
            "iss": f"{PROJECT}/auth/v1",
            "exp": int((utcnow() + timedelta(hours=1)).timestamp()),
        },
        key="",
        algorithm="none",
    )
    assert client.get("/v1/account", headers=_auth(unsigned)).status_code == 401


def test_a_token_without_a_subject_is_rejected(client, legacy_project):
    now = utcnow()
    no_sub = jwt.encode(
        {
            "email": "nobody@example.com",
            "aud": "authenticated",
            "iss": f"{PROJECT}/auth/v1",
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )
    assert client.get("/v1/account", headers=_auth(no_sub)).status_code == 401


def test_an_anonymous_session_cannot_act_on_an_account(client, legacy_project):
    """Supabase can mint anonymous sessions; our anonymous path has no
    account, so an anonymous user holding credits would be a second
    identity model."""
    anon = supabase_token(extra={"is_anonymous": True})
    response = client.get("/v1/account", headers=_auth(anon))
    assert response.status_code == 401
    assert "anonymous" in response.json()["detail"]


def test_an_unverified_email_cannot_claim_an_existing_account(
    client, legacy_project, session
):
    """Otherwise anyone could take over an account by signing up with its
    address through a provider that does not verify email."""
    session.add(User(id="usr_incumbent", email="target@example.com", plan="pro"))
    session.commit()

    attacker = supabase_token(
        sub=str(uuid.uuid4()), email="target@example.com", verified=False
    )
    response = client.get("/v1/account", headers=_auth(attacker))
    assert response.status_code == 401
    assert "already has an account" in response.json()["detail"]

    # And the incumbent is untouched.
    session.expire_all()
    assert session.get(User, "usr_incumbent").plan == "pro"


def test_a_verified_email_does_link_to_the_existing_account(
    client, legacy_project, session
):
    session.add(User(id="usr_known", email="known@example.com", plan="pro"))
    session.commit()

    token = supabase_token(sub=str(uuid.uuid4()), email="known@example.com", verified=True)
    body = client.get("/v1/account", headers=_auth(token)).json()
    assert body["user_id"] == "usr_known"
    assert body["plan"] == "pro"


def test_a_magic_link_session_counts_as_verified(client, legacy_project, session):
    session.add(User(id="usr_magic", email="magic@example.com", plan="starter"))
    session.commit()

    token = supabase_token(
        sub=str(uuid.uuid4()),
        email="magic@example.com",
        verified=False,
        extra={"amr": [{"method": "otp", "timestamp": 1}]},
    )
    body = client.get("/v1/account", headers=_auth(token)).json()
    assert body["user_id"] == "usr_magic"


def test_the_jwks_url_is_derived_from_the_project_url(tmp_env, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "supabase_url", PROJECT)
    assert cfg.jwks_url == f"{PROJECT}/auth/v1/.well-known/jwks.json"
    assert cfg.expected_issuer == f"{PROJECT}/auth/v1"


def test_production_refuses_to_boot_without_a_verification_key(tmp_env, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "environment", "prod")
    with pytest.raises(RuntimeError, match="verify Supabase tokens"):
        cfg.check()


def test_production_refuses_to_boot_with_dev_auth_on(tmp_env, monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "environment", "prod")
    monkeypatch.setattr(cfg, "dev_auth_enabled", True)
    with pytest.raises(RuntimeError, match="auth bypass"):
        cfg.check()


def test_the_dev_route_is_not_mounted_by_default(client):
    """It is an auth bypass. Off unless explicitly switched on."""
    response = client.post("/v1/dev/session", json={"email": "someone@example.com"})
    assert response.status_code == 404
