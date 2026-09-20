"""Authentication: API keys and the auth provider's JWT.

Two callers, one identity type. API keys are `v4u_live_...`; we store the
SHA-256 hash and show the plaintext exactly once (§6). JWTs are verified
against the provider's JWKS — we do not hand-roll auth, and we do not trust
an unverified `sub`.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import errors
from app.config import settings
from app.db import get_session
from app.models import ApiKey, User, utcnow

KEY_PREFIX = "v4u_live_"


@dataclass(frozen=True)
class Principal:
    user: User | None
    api_key: ApiKey | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.user is None

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def is_api(self) -> bool:
        return self.api_key is not None


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, sha256, prefix). The plaintext is never stored."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_key(raw), raw[: len(KEY_PREFIX) + 6]


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _verify_jwt(token: str) -> dict[str, Any]:
    cfg = settings()
    if cfg.jwt_jwks_url:
        client = jwt.PyJWKClient(cfg.jwt_jwks_url)
        signing_key = client.get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=cfg.jwt_audience or None,
            issuer=cfg.jwt_issuer or None,
        )
        return claims
    if cfg.is_production:  # pragma: no cover - blocked by Settings.check()
        raise errors.unauthorized("no JWKS configured")
    # Dev/test only: a symmetric secret so the web app can be exercised
    # without standing up an identity provider.
    return dict(jwt.decode(token, cfg.jwt_dev_secret, algorithms=["HS256"]))


def _principal_from_bearer(token: str, session: Session) -> Principal:
    if token.startswith(KEY_PREFIX):
        record = session.execute(
            select(ApiKey).where(ApiKey.key_hash == hash_key(token))
        ).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            raise errors.unauthorized("invalid API key")
        record.last_used_at = utcnow()
        user = session.get(User, record.user_id)
        if user is None:  # pragma: no cover - FK makes this unreachable
            raise errors.unauthorized("invalid API key")
        return Principal(user=user, api_key=record)

    try:
        claims = _verify_jwt(token)
    except errors.ProblemError:
        raise
    except Exception as exc:
        raise errors.unauthorized(f"invalid token: {exc}") from exc

    email = claims.get("email")
    subject = claims.get("sub")
    if not subject:
        raise errors.unauthorized("token has no subject")

    user = session.execute(select(User).where(User.id == subject)).scalar_one_or_none()
    if user is None and email:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        # First sight of a valid identity: create the account. The identity
        # provider is the source of truth for who this is.
        user = User(id=str(subject), email=email or f"{subject}@users.noreply")
        session.add(user)
        session.flush()
    return Principal(user=user)


def optional_principal(
    request: Request, session: Session = Depends(get_session)
) -> Principal:
    """Anonymous is a valid state: previews do not require an account (§7)."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return Principal(user=None)
    return _principal_from_bearer(header[7:].strip(), session)


def required_principal(principal: Principal = Depends(optional_principal)) -> Principal:
    if principal.user is None:
        raise errors.unauthorized()
    return principal


def client_ip(request: Request) -> str:
    """Trust `X-Forwarded-For` only for its first hop, behind our own proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"
