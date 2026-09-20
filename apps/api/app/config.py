"""Service configuration.

Everything is env-driven. Defaults are development-safe, never
production-safe: anything that would be dangerous to get wrong silently
(signing secrets, the storage bucket) has no usable default and is checked
at startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VEC_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    database_url: str = "sqlite+pysqlite:///./vectorize.db"
    redis_url: str = "redis://127.0.0.1:6379/0"

    # Storage. The local backend exists so the whole service can run and be
    # tested without cloud credentials; it is refused outside dev/test.
    storage_backend: Literal["r2", "local"] = "local"
    storage_local_dir: str = "./.storage"
    r2_bucket: str = ""
    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_region: str = "auto"

    # §4.3 presigned uploads
    upload_url_ttl_s: int = 600
    download_url_ttl_s: int = 3600
    max_upload_bytes: int = 25 * 1024 * 1024

    # §6 sync/async
    sync_hold_window_s: float = 8.0

    # §8 retention
    retention_free_hours: int = 24
    retention_paid_days: int = 30

    # §8 preview limits, stated once
    preview_limit_anonymous_per_hour: int = 20
    preview_limit_signed_in_per_hour: int = 60
    preview_turnstile_after: int = 5
    tile_limit_per_hour: int = 600

    # Auth
    jwt_issuer: str = ""
    jwt_audience: str = ""
    jwt_jwks_url: str = ""
    jwt_dev_secret: str = "dev-only-not-a-secret"

    # §5: a plain hash of an IPv4 address is reversible by brute force in
    # seconds, so ip_hash is an HMAC under a daily-rotating secret.
    ip_hash_secret: str = "dev-only-not-a-secret"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    webhook_signing_secret: str = "dev-only-not-a-secret"

    free_monthly_downloads: int = 3

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "prod")

    def check(self) -> None:
        """Fail at startup rather than at the first paid request."""
        if not self.is_production:
            return
        problems = []
        if self.storage_backend != "r2":
            problems.append("VEC_STORAGE_BACKEND must be 'r2' in production")
        if not self.r2_bucket or not self.r2_endpoint_url:
            problems.append("R2 bucket/endpoint are not configured")
        for name in ("ip_hash_secret", "webhook_signing_secret", "jwt_dev_secret"):
            if getattr(self, name).startswith("dev-only"):
                problems.append(f"VEC_{name.upper()} still holds its development default")
        if not self.jwt_jwks_url:
            problems.append("VEC_JWT_JWKS_URL is not configured")
        if not self.stripe_webhook_secret:
            problems.append("VEC_STRIPE_WEBHOOK_SECRET is not configured")
        if problems:
            raise RuntimeError("unsafe configuration: " + "; ".join(problems))


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
