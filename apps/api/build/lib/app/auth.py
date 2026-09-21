"""Authentication: API keys and Supabase session JWTs.

Two callers, one identity type. API keys are `v4u_live_...`; we store the
SHA-256 hash and show the plaintext exactly once (§6).

Session tokens come from Supabase Auth. We verify them ourselves rather
than calling Supabase on every request — a network round trip per API call
would put someone else's uptime inside our p95 — but verification is real:
signature, issuer, audience and expiry, against the project's published
keys. An unverified `sub` is never trusted, because `sub` is the account.

Supabase signs one of two ways depending on the project, and both are
supported so a project can migrate without redeploying this service:
asymmetric keys published at the JWKS endpoint, or the legacy shared HS256
secret.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from functools import lru_cache
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


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    """Cached: PyJWKClient caches keys, and a new client per request would
    fetch the key set on every call."""
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600)


# Fixed per branch. Never read the algorithm from the token's own header to
# decide *how* to verify — that is how "alg: none" and HS256/RS256
# confusion attacks work. The header only selects which configured key is
# the right one to try, and each branch then pins its own algorithm list.
ASYMMETRIC_ALGORITHMS = ("RS256", "ES256")
SYMMETRIC_ALGORITHMS = ("HS256",)


def _verify_jwt(token: str) -> dict[str, Any]:
    cfg = settings()

    try:
        header_alg = str(jwt.get_unverified_header(token).get("alg", ""))
    except jwt.PyJWTError as exc:
        raise errors.unauthorized(f"malformed token: {exc}") from exc

    audience = cfg.jwt_audience or None
    issuer = cfg.expected_issuer or None
    # Supabase always sets these; a token without them is not one of ours
    # and should not be accepted just because the signature checks out.
    required: Any = {"require": ["exp", "sub"]}

    if header_alg in ASYMMETRIC_ALGORITHMS and cfg.jwks_url:
        signing_key = _jwks_client(cfg.jwks_url).get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(ASYMMETRIC_ALGORITHMS),
            audience=audience,
            issuer=issuer,
            options=required,
        )
        return claims

    if header_alg in SYMMETRIC_ALGORITHMS and cfg.supabase_jwt_secret:
        # Legacy Supabase projects sign with the project's shared secret.
        # Once a project has migrated to asymmetric keys, *remove* the
        # secret: leaving it configured keeps a second way to mint tokens
        # alive long after anyone remembers it exists.
        return dict(
            jwt.decode(
                token,
                cfg.supabase_jwt_secret,
                algorithms=list(SYMMETRIC_ALGORITHMS),
                audience=audience,
                issuer=issuer,
                options=required,
            )
        )

    if cfg.is_production:  # pragma: no cover - blocked by Settings.check()
        raise errors.unauthorized("no Supabase verification key for this token")

    # Development only: a symmetric secret so the whole signed-in flow can
    # be exercised without standing up a Supabase project. Tokens minted
    # here carry no issuer, so that check is dropped with it.
    return dict(
        jwt.decode(
            token,
            cfg.jwt_dev_secret,
            algorithms=list(SYMMETRIC_ALGORITHMS),
            audience=audience,
            options={"verify_iss": False, "require": ["exp", "sub"]},
        )
    )


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

    subject = claims.get("sub")
    if not subject:
        raise errors.unauthorized("token has no subject")

    # Supabase can mint anonymous sessions. Our anonymous path is genuinely
    # anonymous — no account, no credits — so an anonymous Supabase user
    # holding a credit balance would be a second, confusing identity model.
    if claims.get("is_anonymous"):
        raise errors.unauthorized("anonymous sessions cannot be used for account actions")

    email = claims.get("email")
    user = session.execute(select(User).where(User.id == subject)).scalar_one_or_none()

    if user is None and email:
        incumbent = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if incumbent is not None:
            if not _email_is_verified(claims):
                # Linking by email is only safe when the provider says the
                # address was actually proven. Refuse rather than quietly
                # opening a second account on the same address: that would
                # collide on `users.email` anyway, and a 500 is a worse
                # answer than a clear one.
                raise errors.unauthorized(
                    "that address already has an account — sign in with a verified method"
                )
            user = incumbent

    if user is None:
        # First sight of a valid identity: create the account. The identity
        # provider is the source of truth for who this is, and `sub` is the
        # account key — the email is a label that can change.
        user = User(id=str(subject), email=email or f"{subject}@users.noreply")
        session.add(user)
        session.flush()
    elif email and user.email != email:
        # Supabase allows an address change; follow it rather than leaving
        # receipts going to the old one.
        user.email = email

    return Principal(user=user)


def _email_is_verified(claims: dict[str, Any]) -> bool:
    """Supabase reports this in `user_metadata`, and older tokens omit it."""
    if claims.get("email_verified") is True:
        return True
    metadata = claims.get("user_metadata")
    if isinstance(metadata, dict) and metadata.get("email_verified") is True:
        return True
    # A magic-link session is proof of the address by construction.
    return claims.get("amr") is not None and any(
        entry.get("method") in ("otp", "magiclink", "email")
        for entry in claims.get("amr", [])
        if isinstance(entry, dict)
    )


def optional_principal(request: Request, session: Session = Depends(get_session)) -> Principal:
    """Anonymous is a valid state: previews do not require an account (§7)."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return Principal(user=None)
    return _principal_from_bearer(header[7:].strip(), session)


def required_principal(principal: Principal = Depends(optional_principal)) -> Principal:
    if principal.user is None:
        raise errors.unauthorized()
    return principal


def enforce_api_rate_limit(request: Request, principal: Principal) -> None:
    """Per-key request rate, by plan (§6: 429 with Retry-After).

    Keyed on the API key rather than the user, so one runaway integration
    cannot starve that customer's other keys — and so revoking the noisy
    key is a complete fix.

    Browser sessions are exempt here: the interactive paths have their own
    limits (previews, tiles) tuned for humans, and a shared per-user rate
    would make a person opening several tabs look like an attack.
    """
    from app import errors, ratelimit
    from app.catalog import plan_for

    if principal.api_key is None or principal.user is None:
        return

    limit = plan_for(principal.user.plan).rate_per_minute
    decision = ratelimit.hit("api", principal.api_key.id, limit, window_s=60)

    # Standard headers, so a client can back off before being told to.
    request.state.rate_limit = (limit, decision.remaining, decision.retry_after)
    if not decision.allowed:
        raise errors.rate_limited(
            decision.retry_after,
            f"{limit} requests per minute on the {principal.user.plan} plan",
        )


def rate_limited_principal(
    request: Request, principal: Principal = Depends(required_principal)
) -> Principal:
    """`required_principal`, plus the per-key rate limit."""
    enforce_api_rate_limit(request, principal)
    return principal


def client_ip(request: Request) -> str:
    """Trust `X-Forwarded-For` only for its first hop, behind our own proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"
