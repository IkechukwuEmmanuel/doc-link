"""Phase 6 rate limiting. Exercises the token-bucket algorithm and the
creation endpoint with an injected in-memory backend."""

import pytest

from app.services import ratelimit
from app.services.ratelimit import Bucket, InMemoryBackend


def test_token_bucket_allows_then_blocks_then_refills():
    backend = InMemoryBackend()
    bucket = Bucket("t", capacity=2, refill_per_sec=1.0)
    # two tokens available at t=0
    assert backend.consume("k", bucket, now=0.0) == 0.0
    assert backend.consume("k", bucket, now=0.0) == 0.0
    # third is denied; retry ~1s
    retry = backend.consume("k", bucket, now=0.0)
    assert retry > 0
    # after enough time, refilled
    assert backend.consume("k", bucket, now=10.0) == 0.0


@pytest.fixture
def inmem_limiter():
    ratelimit.set_backend(InMemoryBackend())
    yield
    ratelimit.set_backend(None)  # restore fail-open


async def test_creation_burst_guard_returns_429(client, inmem_limiter):
    # burst bucket is capacity 1 → second anonymous create within 5s is limited
    first = await client.post("/api/pads", json={})
    assert first.status_code == 201
    second = await client.post("/api/pads", json={})
    assert second.status_code == 429
    assert "retry-after" in {k.lower() for k in second.headers}


async def test_authenticated_create_not_rate_limited(client, inmem_limiter):
    signup = await client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "password123"}
    )
    token = signup.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    # authenticated creation bypasses the anonymous-IP creation limit
    a = await client.post("/api/pads", json={"slug": "auth-one"}, headers=auth)
    b = await client.post("/api/pads", json={"slug": "auth-two"}, headers=auth)
    assert a.status_code == 201
    assert b.status_code == 201


async def test_fail_open_when_no_backend(client):
    # No backend injected (default in tests) → creation is never limited.
    ratelimit.set_backend(None)
    for i in range(3):
        resp = await client.post("/api/pads", json={})
        assert resp.status_code == 201
