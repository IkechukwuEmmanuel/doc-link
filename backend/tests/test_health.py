"""Liveness + readiness endpoints (Part B observability)."""

from app import main


async def test_liveness_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readiness_ok_when_db_reachable(client, monkeypatch):
    async def ok():
        return True

    monkeypatch.setattr(main, "_db_ready", ok)
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"]["database"] == "ok"


async def test_readiness_503_when_db_down(client, monkeypatch):
    async def down():
        return False

    monkeypatch.setattr(main, "_db_ready", down)
    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
    assert resp.json()["checks"]["database"] == "error"
