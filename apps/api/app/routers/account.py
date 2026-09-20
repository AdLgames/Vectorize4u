"""§6 `/v1/account` and API key management (§6, Phase 6 groundwork)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import credits, errors
from app.auth import Principal, generate_api_key, required_principal
from app.db import get_session
from app.models import ApiKey, Job, utcnow
from app.schemas import AccountResponse, ApiKeyCreateRequest, ApiKeyResponse, GrantResponse

router = APIRouter(prefix="/v1", tags=["account"])


@router.get("/account", response_model=AccountResponse)
def account(
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> AccountResponse:
    user = principal.user
    assert user is not None

    # Lapsed grants are expired on read as well as by the sweeper, so the
    # number the user sees is never stale in the optimistic direction.
    credits.expire_lapsed(session, user.id)
    credits.monthly_free_grant(session, user.id, amount=_free_allowance(user.plan))

    since = utcnow() - timedelta(days=30)
    jobs_30d = int(
        session.execute(
            select(func.count(Job.id)).where(Job.user_id == user.id, Job.created_at >= since)
        ).scalar_one()
    )
    credits_30d = int(
        session.execute(
            select(func.coalesce(func.sum(Job.credits_charged), 0)).where(
                Job.user_id == user.id, Job.created_at >= since
            )
        ).scalar_one()
    )

    return AccountResponse(
        user_id=user.id,
        email=user.email,
        plan=user.plan,
        credits=credits.balance(session, user.id),
        grants=[
            GrantResponse(
                id=g.id, source=g.source, amount=g.amount,
                remaining=g.remaining, expires_at=g.expires_at,
            )
            for g in credits.grants_view(session, user.id)
        ],
        usage_30d={"jobs": jobs_30d, "credits": credits_30d},
    )


def _free_allowance(plan: str) -> int:
    from app.config import settings

    return settings().free_monthly_downloads if plan == "free" else 0


@router.get("/account/keys", response_model=list[ApiKeyResponse])
def list_keys(
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> list[ApiKeyResponse]:
    rows = session.execute(
        select(ApiKey).where(ApiKey.user_id == principal.user_id)
    ).scalars().all()
    return [
        ApiKeyResponse(
            id=k.id, key_prefix=k.key_prefix, label=k.label,
            created_at=k.created_at, revoked_at=k.revoked_at,
        )
        for k in rows
    ]


@router.post("/account/keys", response_model=ApiKeyResponse, status_code=201)
def create_key(
    body: ApiKeyCreateRequest,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> ApiKeyResponse:
    """The plaintext is returned exactly once and never stored (§6)."""
    raw, digest, prefix = generate_api_key()
    record = ApiKey(
        user_id=principal.user_id, key_hash=digest, key_prefix=prefix, label=body.label
    )
    session.add(record)
    session.flush()
    return ApiKeyResponse(
        id=record.id, key_prefix=prefix, label=record.label,
        created_at=record.created_at, key=raw,
    )


@router.delete("/account/keys/{key_id}", status_code=204)
def revoke_key(
    key_id: str,
    principal: Principal = Depends(required_principal),
    session: Session = Depends(get_session),
) -> None:
    record = session.get(ApiKey, key_id)
    if record is None or record.user_id != principal.user_id:
        raise errors.not_found("api key")
    record.revoked_at = utcnow()
    session.flush()
