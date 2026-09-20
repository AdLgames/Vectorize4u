"""Service configuration.

Everything is env-driven. Defaults are development-safe, never
production-safe: anything that would be dangerous to get wrong silently
(signing secrets, the storage bucket) has no usable default and is checked
at startup.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    # Where the browser can reach this API. The local storage backend signs
    # download URLs itself, and a relative one would resolve against the
    # *web app's* origin in development, where the two run on different
    # ports. R2 returns absolute URLs, so this is unused in production.
    public_api_url: str = "http://127.0.0.1:8000"
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

    # Auth — Supabase.
    #
    # Supabase signs session JWTs one of two ways depending on the project's
    # age and settings, and both are supported because a project can be
    # migrated between them without the API being redeployed:
    #
    #   asymmetric (current) — ES256/RS256, public keys at the project's
    #     JWKS endpoint. Set `supabase_url` and the endpoint is derived.
    #   shared secret (legacy) — HS256 signed with the project's JWT secret.
    #     Set `supabase_jwt_secret`.
    #
    # The secret is a *signing* key, not an API key: anything holding it can
    # mint a token for any user. It never goes near the browser.
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = "authenticated"
    jwt_jwks_url: str = ""
    jwt_dev_secret: str = "dev-only-not-a-secret"

    # Local sign-in without a Supabase project, for development and the
    # browser test. Refused outright in production (see `check`), and the
    # route that serves it is not even mounted there.
    dev_auth_enabled: bool = False

    # §5: a plain hash of an IPv4 address is reversible by brute force in
    # seconds, so ip_hash is an HMAC under a daily-rotating secret.
    ip_hash_secret: str = "dev-only-not-a-secret"

    # A staging deployment that can convert images but not sell them is a
    # useful thing to have before Stripe exists. Refused in prod below: a
    # production site that silently cannot take money is not a mode
    # anybody wants to discover by accident.
    payments_enabled: bool = True

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Price ids per plan, e.g. {"pack": "price_...", "starter": "price_..."}.
    # Produced by scripts/bootstrap_stripe.py. Referenced by id rather than
    # looked up by name, so a duplicate made in the dashboard can never be
    # picked up silently.
    stripe_prices: dict[str, str] = Field(default_factory=dict)
    # Where Stripe sends the browser back to.
    checkout_success_url: str = "http://localhost:3000/checkout/success"
    checkout_cancel_url: str = "http://localhost:3000/#pricing"
    billing_portal_return_url: str = "http://localhost:3000/account"

    webhook_signing_secret: str = "dev-only-not-a-secret"

    free_monthly_downloads: int = 3

    # §8 cost guardrail. An 8-candidate search's failure mode is a large
    # CPU bill, and the first sign is a day that does not look like the
    # week before it. Empty means log-only, which is the right default for
    # development and the wrong one for production.
    alert_webhook_url: str = ""
    cost_alert_deviation: float = 0.15
    cost_alert_window_days: int = 7
    # Below this much compute in a day, percentages are meaningless — two
    # jobs against a baseline of one is a 100% deviation and nothing else.
    cost_alert_floor_ms: int = 60_000

    @property
    def is_production(self) -> bool:
        return self.environment in ("staging", "prod")

    @property
    def jwks_url(self) -> str:
        """The project's JWKS endpoint, explicit or derived from the URL."""
        if self.jwt_jwks_url:
            return self.jwt_jwks_url
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        return ""

    @property
    def expected_issuer(self) -> str:
        if self.jwt_issuer:
            return self.jwt_issuer
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1"
        return ""

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
        if not self.jwks_url and not self.supabase_jwt_secret:
            problems.append(
                "no way to verify Supabase tokens: set VEC_SUPABASE_URL "
                "(asymmetric keys) or VEC_SUPABASE_JWT_SECRET (legacy HS256)"
            )
        if self.dev_auth_enabled:
            problems.append("VEC_DEV_AUTH_ENABLED is on — it is a total auth bypass")
        if not self.payments_enabled:
            if self.environment == "prod":
                problems.append(
                    "VEC_PAYMENTS_ENABLED is off — allowed in staging, never in production"
                )
            if problems:
                raise RuntimeError("unsafe configuration: " + "; ".join(problems))
            return
        if not self.stripe_webhook_secret:
            problems.append("VEC_STRIPE_WEBHOOK_SECRET is not configured")
        if not self.stripe_secret_key:
            problems.append("VEC_STRIPE_SECRET_KEY is not configured")
        if self.stripe_secret_key.startswith("sk_test_"):
            problems.append("VEC_STRIPE_SECRET_KEY is a test key")
        missing = [p for p in ("pack", "starter", "pro") if not self.stripe_prices.get(p)]
        if missing:
            problems.append(f"no Stripe price configured for: {', '.join(missing)}")
        for name in ("checkout_success_url", "checkout_cancel_url", "billing_portal_return_url"):
            if "localhost" in getattr(self, name):
                problems.append(f"VEC_{name.upper()} still points at localhost")
        if problems:
            raise RuntimeError("unsafe configuration: " + "; ".join(problems))


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
