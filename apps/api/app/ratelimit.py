"""§8 preview and tile limits.

Redis-backed fixed windows, with an in-process fallback so the service runs
and is testable without Redis. The fallback is per-worker and therefore not
a real limit: it is refused in production.

Preview limits, stated once and only here: 20/hour anonymous, 60/hour
signed-in, Turnstile after 5 anonymous previews, tiles limited separately.
Marketing copy says "free previews", never "unlimited".
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import settings


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: int
    count: int


class _MemoryBackend:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}

    def incr(self, key: str, window_s: int) -> tuple[int, int]:
        now = time.time()
        count, expires = self._counts.get(key, (0, now + window_s))
        if expires <= now:
            count, expires = 0, now + window_s
        count += 1
        self._counts[key] = (count, expires)
        return count, int(expires - now)

    def reset(self) -> None:
        self._counts.clear()


class _RedisBackend:
    def __init__(self, url: str) -> None:
        import redis

        self.client = redis.Redis.from_url(url, decode_responses=True)

    def incr(self, key: str, window_s: int) -> tuple[int, int]:
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        if ttl is None or ttl < 0:
            self.client.expire(key, window_s)
            ttl = window_s
        return int(count), int(ttl)

    def reset(self) -> None:  # pragma: no cover - not used in production
        pass


_backend: _MemoryBackend | _RedisBackend | None = None


def backend() -> _MemoryBackend | _RedisBackend:
    global _backend
    if _backend is None:
        cfg = settings()
        if cfg.environment in ("test", "dev") or not cfg.redis_url:
            if cfg.is_production:
                raise RuntimeError("the in-memory rate limiter is refused in production")
            _backend = _MemoryBackend()
        else:
            _backend = _RedisBackend(cfg.redis_url)
    return _backend


def reset() -> None:
    """Test hook."""
    global _backend
    if isinstance(_backend, _MemoryBackend):
        _backend.reset()
    _backend = None


def hit(bucket: str, identity: str, limit: int, window_s: int = 3600) -> Decision:
    count, ttl = backend().incr(f"rl:{bucket}:{identity}:{_window(window_s)}", window_s)
    return Decision(
        allowed=count <= limit,
        remaining=max(0, limit - count),
        retry_after=max(1, ttl),
        count=count,
    )


def peek_preview_count(identity: str, window_s: int = 3600) -> int:
    """How many previews this identity has taken, without consuming one."""
    key = f"rl:preview:{identity}:{_window(window_s)}"
    backend_ = backend()
    if isinstance(backend_, _MemoryBackend):
        return backend_._counts.get(key, (0, 0.0))[0]
    value = backend_.client.get(key)  # type: ignore[union-attr]
    return int(value) if value else 0  # type: ignore[arg-type]


def _window(window_s: int) -> int:
    return int(time.time()) // window_s


def ip_hash(ip: str) -> str:
    """HMAC-SHA256 under a **daily-rotating** secret (§5).

    A plain hash of an IPv4 address is reversible by brute force in seconds
    — the whole space is 2^32 and a laptop covers it over lunch.
    """
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    secret = f"{settings().ip_hash_secret}:{day}".encode()
    return hmac.new(secret, ip.encode(), hashlib.sha256).hexdigest()
