"""Signed-URL endpoints for the local storage backend.

These exist so dev and tests exercise the same "short-lived signed URL"
path the R2 backend uses in production. With `VEC_STORAGE_BACKEND=r2` the
signed URLs point at R2 and these routes are never called.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app import errors
from app.storage import LocalStorage, ObjectNotFound, storage

router = APIRouter(prefix="/v1/files", tags=["files"])


def _local() -> LocalStorage:
    backend = storage()
    if not isinstance(backend, LocalStorage):
        raise errors.not_found("route")
    return backend


@router.put("/upload")
async def put_object(request: Request, key: str, expires: int, signature: str) -> Response:
    backend = _local()
    if not backend.verify(key, expires, signature):
        raise errors.forbidden("expired or invalid upload URL")
    body = await request.body()
    backend.put(
        key,
        body,
        content_type=request.headers.get("content-type", "application/octet-stream"),
    )
    return Response(status_code=200)


@router.get("/download")
def get_object(key: str, expires: int, signature: str, filename: str | None = None) -> Response:
    backend = _local()
    if not backend.verify(key, expires, signature):
        raise errors.forbidden("expired or invalid download URL")
    try:
        data = backend.get(key)
        info = backend.head(key)
    except ObjectNotFound as exc:
        # A deleted job's files are unreachable immediately (§13).
        raise errors.not_found("file") from exc
    headers = {}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=data, media_type=info.content_type, headers=headers)
