"""§4.3 — presigned direct-to-R2 uploads.

Uploads never pass through Vercel (≈4.5 MB body cap) and batches never
travel as one multipart request: 500 × 25 MB is 12.5 GB.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import errors
from app.auth import Principal, optional_principal
from app.config import settings
from app.db import get_session
from app.jobs import storage_tier
from app.models import Upload, new_id
from app.schemas import UploadRequest, UploadResponse
from app.storage import object_key, storage

router = APIRouter(prefix="/v1", tags=["uploads"])

ALLOWED_CONTENT_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/bmp",
    "image/gif", "image/tiff", "image/heic", "image/heif",
    "application/octet-stream",
}


@router.post("/uploads", response_model=UploadResponse)
def create_upload(
    body: UploadRequest,
    principal: Principal = Depends(optional_principal),
    session: Session = Depends(get_session),
) -> UploadResponse:
    cfg = settings()
    if body.content_length > cfg.max_upload_bytes:
        raise errors.too_large(
            f"{body.content_length} bytes exceeds the {cfg.max_upload_bytes} byte limit"
        )
    content_type = body.content_type.split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise errors.ProblemError(
            415, "unsupported_media_type", f"{content_type} is not an accepted image type"
        )

    upload_id = new_id("upl")
    key = object_key(storage_tier(principal), "source", upload_id, "source.bin")  # type: ignore[arg-type]
    presigned = storage().presign_put(
        key,
        content_type=content_type,
        content_length=body.content_length,
        expires_in=cfg.upload_url_ttl_s,
    )

    session.add(
        Upload(
            id=upload_id,
            user_id=principal.user_id,
            key=key,
            content_type=content_type,
            declared_bytes=body.content_length,
        )
    )
    session.flush()

    return UploadResponse(
        upload_id=upload_id,
        put_url=presigned.url,
        headers=presigned.headers,
        expires_in=presigned.expires_in,
    )
