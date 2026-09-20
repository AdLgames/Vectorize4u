"""A local sign-in that does not need a Supabase project.

This exists so the whole signed-in flow — unlock, batch, account — can be
run and browser-tested without standing up an identity provider, and so a
contributor's first `make api && make web` is a working app rather than a
sign-in wall.

It is an **auth bypass**. Three separate things have to be true before it
does anything:

  1. `VEC_DEV_AUTH_ENABLED=1` — off by default.
  2. The environment is not staging or prod.
  3. `Settings.check()` refuses to boot production at all when (1) is set.

The router is not even mounted outside development.
"""

from __future__ import annotations

import logging
import uuid

import jwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app import errors
from app.config import settings
from app.db import get_session
from app.models import utcnow

log = logging.getLogger("vectorize.api.dev_auth")

router = APIRouter(prefix="/v1/dev", tags=["dev"])

TOKEN_TTL_S = 60 * 60 * 12


class DevSessionRequest(BaseModel):
    # Deliberately not EmailStr: that pulls `email-validator` into the
    # production dependency set for the sake of a route that only exists in
    # development. A shape check is enough to keep test data sane.
    email: str

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str) -> str:
        cleaned = value.strip()
        if "@" not in cleaned or len(cleaned) < 3:
            raise ValueError("not an email address")
        return cleaned


class DevSessionResponse(BaseModel):
    access_token: str
    email: str
    user_id: str
    expires_in: int


@router.post("/session", response_model=DevSessionResponse)
def dev_session(
    body: DevSessionRequest,
    session: Session = Depends(get_session),
) -> DevSessionResponse:
    cfg = settings()
    if cfg.is_production or not cfg.dev_auth_enabled:
        # Defence in depth: the router should not be mounted here at all.
        raise errors.not_found("route")

    from sqlalchemy import select

    from app.models import User

    existing = session.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    # A stable id per email so signing in twice returns the same account,
    # and so it looks like the Supabase UUID it stands in for.
    user_id = existing.id if existing else str(uuid.uuid5(uuid.NAMESPACE_URL, f"dev:{body.email}"))

    now = int(utcnow().timestamp())
    token = jwt.encode(
        {
            "sub": user_id,
            "email": body.email,
            "aud": cfg.jwt_audience or "authenticated",
            "role": "authenticated",
            "iat": now,
            "exp": now + TOKEN_TTL_S,
            "user_metadata": {"email_verified": True},
        },
        cfg.jwt_dev_secret,
        algorithm="HS256",
    )
    log.warning("issued a development session for %s — this is not real auth", body.email)
    return DevSessionResponse(
        access_token=token, email=body.email, user_id=user_id, expires_in=TOKEN_TTL_S
    )
