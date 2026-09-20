"""Object storage: R2 in production, a local directory for dev and tests.

Two rules from §8 are enforced here rather than left to convention:

- **Outputs are served via short-lived signed URLs (1 hour), never from our
  own origin path.**
- **Retention prefixes.** Free work goes under `free/`, paid under `paid/`,
  because the R2 lifecycle rules are the backstop for the retention promise.
  A dead sweeper must not be able to break it, so the prefix is chosen at
  write time and cannot be corrected later.

No long-lived CDN cache: every output is a unique file downloaded once or
twice by one person, so the hit rate is inherently near zero and there is
nothing to win. Caching private artwork under a path-only key with
`immutable, max-age=31536000` would serve deleted files for a year.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from app.config import settings

Tier = Literal["free", "paid"]


@dataclass(frozen=True)
class PresignedUpload:
    key: str
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    content_type: str


class StorageError(Exception):
    pass


class ObjectNotFound(StorageError):
    pass


def object_key(tier: Tier, kind: str, job_or_upload_id: str, name: str) -> str:
    """`{tier}/{kind}/{id}/{name}` — the tier prefix drives lifecycle rules."""
    return f"{tier}/{kind}/{job_or_upload_id}/{name}"


class Storage(ABC):
    @abstractmethod
    def presign_put(
        self, key: str, *, content_type: str, content_length: int, expires_in: int
    ) -> PresignedUpload: ...

    @abstractmethod
    def presign_get(self, key: str, *, expires_in: int, filename: str | None = None) -> str: ...

    @abstractmethod
    def head(self, key: str) -> ObjectInfo: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int: ...


class LocalStorage(Storage):
    """Filesystem-backed, for dev and tests.

    Signed URLs are real HMACs over key+expiry, so the endpoint that serves
    them exercises the same verification path as production does.
    """

    def __init__(self, root: str | Path, secret: str, base_url: str = "/v1/files") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.secret = secret.encode()
        self.base_url = base_url

    def _path(self, key: str) -> Path:
        # Defence in depth: a key is server-generated, but a traversal here
        # would be a filesystem write outside the store.
        if ".." in key.split("/"):
            raise StorageError(f"unsafe key: {key}")
        return self.root / key

    def _sign(self, key: str, expires: int) -> str:
        mac = hmac.new(self.secret, f"{key}:{expires}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    def verify(self, key: str, expires: int, signature: str) -> bool:
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(self._sign(key, expires), signature)

    def presign_put(
        self, key: str, *, content_type: str, content_length: int, expires_in: int
    ) -> PresignedUpload:
        expires = int(time.time()) + expires_in
        signature = self._sign(key, expires)
        url = (
            f"{self.base_url}/upload?key={quote(key)}"
            f"&expires={expires}&signature={signature}"
        )
        return PresignedUpload(
            key=key,
            url=url,
            method="PUT",
            headers={"Content-Type": content_type, "Content-Length": str(content_length)},
            expires_in=expires_in,
        )

    def presign_get(self, key: str, *, expires_in: int, filename: str | None = None) -> str:
        expires = int(time.time()) + expires_in
        signature = self._sign(key, expires)
        url = f"{self.base_url}/download?key={quote(key)}&expires={expires}&signature={signature}"
        if filename:
            url += f"&filename={quote(filename)}"
        return url

    def head(self, key: str) -> ObjectInfo:
        path = self._path(key)
        if not path.exists():
            raise ObjectNotFound(key)
        meta = path.with_suffix(path.suffix + ".type")
        content_type = meta.read_text() if meta.exists() else "application/octet-stream"
        return ObjectInfo(key=key, size=path.stat().st_size, content_type=content_type)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise ObjectNotFound(key)
        return path.read_bytes()

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.with_suffix(path.suffix + ".type").write_text(content_type)

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        path.with_suffix(path.suffix + ".type").unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        target = self._path(prefix)
        if not target.exists():
            return 0
        count = sum(1 for p in target.rglob("*") if p.is_file() and not p.name.endswith(".type"))
        shutil.rmtree(target)
        return count


class R2Storage(Storage):
    """Cloudflare R2 over the S3 API. Zero egress fees, S3-compatible signing."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        cfg = settings()
        self.bucket = cfg.r2_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=cfg.r2_endpoint_url,
            aws_access_key_id=cfg.r2_access_key_id,
            aws_secret_access_key=cfg.r2_secret_access_key,
            region_name=cfg.r2_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def presign_put(
        self, key: str, *, content_type: str, content_length: int, expires_in: int
    ) -> PresignedUpload:
        # Content-Length and Content-Type are signed in: without them the
        # client can upload any size and any type to a URL we issued.
        url = self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": content_length,
            },
            ExpiresIn=expires_in,
        )
        return PresignedUpload(
            key=key,
            url=url,
            method="PUT",
            headers={"Content-Type": content_type, "Content-Length": str(content_length)},
            expires_in=expires_in,
        )

    def presign_get(self, key: str, *, expires_in: int, filename: str | None = None) -> str:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        url: str = self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_in
        )
        return url

    def head(self, key: str) -> ObjectInfo:
        from botocore.exceptions import ClientError

        try:
            meta = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise ObjectNotFound(key) from exc
        return ObjectInfo(
            key=key,
            size=int(meta["ContentLength"]),
            content_type=meta.get("ContentType", "application/octet-stream"),
        )

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise ObjectNotFound(key) from exc
        body: bytes = obj["Body"].read()
        return body

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> int:
        paginator = self.client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                deleted += len(keys)
        return deleted


_storage: Storage | None = None


def storage() -> Storage:
    global _storage
    if _storage is None:
        cfg = settings()
        if cfg.storage_backend == "r2":
            _storage = R2Storage()
        else:
            if cfg.is_production:
                raise RuntimeError("the local storage backend is refused in production")
            _storage = LocalStorage(cfg.storage_local_dir, cfg.webhook_signing_secret)
    return _storage


def reset_storage() -> None:
    """Test hook."""
    global _storage
    _storage = None
