"""Token-bucket rate limiting. Phase 6.

Two concerns, one mechanism. A token bucket models a steady refill rate with a
burst capacity, which maps directly onto the PRD §5.4 figures:

  - pad creation:  10 / IP / hour      (capacity 10, refill 10/3600 per sec)
                 + 1 / 5 sec burst     (capacity 1,  refill 1/5 per sec)
  - WS edits:      60 / min / conn     (capacity 60, refill 1 per sec)

Keys are derived from a salted SHA-256 of the client IP — raw IPs are never
stored (PRD §6.4).

Backend selection & degradation:
  - In production ``init()`` pings Redis; if reachable, limits are enforced
    cross-process via Redis. Redis is the shared store so limits hold across
    multiple app instances.
  - If Redis is unreachable (or ``init()`` was never called, as in the test
    harness where the ASGI lifespan doesn't run), the limiter **fails open** —
    requests are allowed. Rate limiting is best-effort abuse prevention, not a
    security control, so an infra outage must not take down pad creation.
  - Tests exercise the algorithm by injecting an in-memory backend directly.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings

settings = get_settings()


# --------------------------------------------------------------------------- #
# Bucket definitions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Bucket:
    name: str
    capacity: float
    refill_per_sec: float


def _creation_buckets() -> list[Bucket]:
    hourly = settings.rl_create_per_hour
    burst_seconds = settings.rl_create_burst_seconds
    return [
        Bucket("create-hour", capacity=hourly, refill_per_sec=hourly / 3600.0),
        Bucket("create-burst", capacity=1, refill_per_sec=1.0 / burst_seconds),
    ]


def _edit_bucket() -> Bucket:
    per_min = settings.rl_edit_per_min
    return Bucket("edit", capacity=per_min, refill_per_sec=per_min / 60.0)


def _pin_bucket() -> Bucket:
    attempts = settings.rl_pin_attempts_per_window
    window = settings.rl_pin_window_seconds
    return Bucket("pin", capacity=attempts, refill_per_sec=attempts / window)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class InMemoryBackend:
    """Per-process token-bucket store. Used for tests and as a typed reference."""

    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float]] = {}

    def consume(self, key: str, bucket: Bucket, now: float | None = None) -> float:
        """Take one token. Return 0 if allowed, else seconds until one is free."""
        now = time.monotonic() if now is None else now
        tokens, last = self._state.get(key, (bucket.capacity, now))
        tokens = min(bucket.capacity, tokens + (now - last) * bucket.refill_per_sec)
        if tokens >= 1.0:
            self._state[key] = (tokens - 1.0, now)
            return 0.0
        self._state[key] = (tokens, now)
        return (1.0 - tokens) / bucket.refill_per_sec


class RedisBackend:
    """Redis-backed token bucket via an atomic Lua script (cross-process safe)."""

    # KEYS[1] = bucket key; ARGV = capacity, refill_per_sec, now (epoch secs)
    _LUA = """
    local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
    local capacity = tonumber(ARGV[1])
    local refill = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local tokens = tonumber(data[1])
    local ts = tonumber(data[2])
    if tokens == nil then tokens = capacity; ts = now end
    tokens = math.min(capacity, tokens + (now - ts) * refill)
    local retry = 0
    if tokens >= 1 then
        tokens = tokens - 1
    else
        retry = (1 - tokens) / refill
    end
    redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
    local ttl = math.ceil(capacity / refill)
    redis.call('EXPIRE', KEYS[1], ttl)
    return tostring(retry)
    """

    def __init__(self, client) -> None:
        self._client = client

    async def consume(self, key: str, bucket: Bucket) -> float:
        retry = await self._client.eval(
            self._LUA,
            1,
            key,
            bucket.capacity,
            bucket.refill_per_sec,
            time.time(),
        )
        return float(retry)


# Module-level backend. None => fail open (allow everything).
_backend: InMemoryBackend | RedisBackend | None = None


async def init() -> None:
    """Wire up Redis if reachable. Called from the app lifespan. Fails open."""
    global _backend
    if not settings.rate_limit_enabled:
        _backend = None
        return
    try:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        await client.ping()
        _backend = RedisBackend(client)
    except Exception:
        # Redis missing/unreachable — degrade to fail-open rather than block.
        _backend = None


def set_backend(backend) -> None:
    """Test hook: inject a backend (e.g. InMemoryBackend) directly."""
    global _backend
    _backend = backend


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"{settings.ip_hash_salt}:{ip}".encode()).hexdigest()


def client_ip(request: Request) -> str:
    """Resolve the client IP for rate-limit keying.

    ``X-Forwarded-For`` is appended left-to-right by each proxy, so the rightmost
    entries are the ones added by *our* infrastructure and the leftmost are
    whatever the original client (possibly an attacker) supplied. We trust only
    the entry added by the outermost of ``trusted_proxy_hops`` proxies — i.e.
    ``parts[-hops]`` — which ignores any forged prefix a client tacks on. With the
    default of 0 trusted hops we ignore the header entirely and use the direct
    peer IP, which cannot be spoofed (AUDIT H1)."""
    hops = settings.trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if len(parts) >= hops:
                return parts[-hops]
            # Chain shorter than the configured hop count → it didn't traverse the
            # expected proxies; fall back to the un-spoofable peer rather than
            # trusting a too-short (likely forged) header.
    return request.client.host if request.client else "unknown"


async def _consume(key: str, bucket: Bucket) -> float:
    if _backend is None:
        return 0.0  # fail open
    result = _backend.consume(f"rl:{bucket.name}:{key}", bucket)
    if hasattr(result, "__await__"):
        return await result  # RedisBackend (coroutine)
    return result  # InMemoryBackend (sync)


async def check_pad_creation(request: Request) -> int | None:
    """Return None if allowed, else an integer ``Retry-After`` (seconds)."""
    key = hash_ip(client_ip(request))
    worst = 0.0
    for bucket in _creation_buckets():
        retry = await _consume(key, bucket)
        worst = max(worst, retry)
    if worst > 0:
        return max(1, int(worst + 0.999))
    return None


async def check_ws_edit(conn_id: str) -> int | None:
    """Per-connection WS edit limit. None if allowed, else seconds to wait."""
    retry = await _consume(conn_id, _edit_bucket())
    if retry > 0:
        return max(1, int(retry + 0.999))
    return None


async def check_pin_attempt(pad_id: str, request: Request) -> int | None:
    """Strict per-pad-per-IP PIN attempt limiter (brute-force defense).

    None if allowed, else an integer ``Retry-After`` (seconds). Keyed by the
    pad id + salted-hashed IP so guessing one pad's PIN can't exhaust another's.
    """
    key = f"{pad_id}:{hash_ip(client_ip(request))}"
    retry = await _consume(key, _pin_bucket())
    if retry > 0:
        return max(1, int(retry + 0.999))
    return None
