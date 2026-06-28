"""Object storage backed by Supabase Storage. Phase 3 (re-platformed onto Supabase).

Files are proxied through the backend: bytes are put here after cap checks and
streamed back out only once a file is marked clean. This module is a thin httpx
wrapper over Supabase Storage's REST API (same pattern as ``supabase_auth.py``),
authenticating with the service-role key so access is governed entirely by our own
permission checks — the bucket is private and is never exposed via a public URL.

The public interface (``ensure_bucket`` / ``put_object`` / ``get_object`` /
``delete_object``) is unchanged from the previous S3 implementation, so nothing
else in the app — file routes, access control, the malware-scan flow — changes.
See DECISIONS.md (this reverses the earlier "S3-compatible storage" decision).
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("spacepad.storage")
settings = get_settings()

_TIMEOUT = httpx.Timeout(30.0)


class StorageError(Exception):
    """A Supabase Storage request failed."""


def _base() -> str:
    return f"{settings.supabase_url.rstrip('/')}/storage/v1"


def _headers(content_type: str | None = None) -> dict:
    # Service-role key: bypasses storage RLS, so authorization is enforced by the
    # FastAPI layer (the bucket itself is private). Server-side only.
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def ensure_bucket() -> None:
    """Best-effort confirm the private bucket exists. Never fatal to startup — a
    storage hiccup shouldn't block boot; upload/download surface errors at call
    time, and readiness is gated on the DB, not storage."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("storage: Supabase not configured; skipping bucket check.")
        return
    bucket = settings.supabase_storage_bucket
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_base()}/bucket/{bucket}", headers=_headers())
            if resp.status_code == 200:
                return
            create = await client.post(
                f"{_base()}/bucket",
                headers=_headers("application/json"),
                json={"id": bucket, "name": bucket, "public": False},
            )
            if create.status_code >= 400 and "exist" not in create.text.lower():
                logger.error(
                    "storage: could not ensure bucket %s: %s %s",
                    bucket, create.status_code, create.text,
                )
    except Exception as exc:  # network/transient — don't kill startup
        logger.warning("storage: bucket check skipped (%s)", exc)


async def put_object(key: str, data: bytes, content_type: str) -> None:
    bucket = settings.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_base()}/object/{bucket}/{key}",
            headers={**_headers(content_type), "x-upsert": "true"},
            content=data,
        )
    if resp.status_code >= 400:
        raise StorageError(f"upload failed ({resp.status_code}): {resp.text}")


async def get_object(key: str) -> bytes:
    bucket = settings.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_base()}/object/authenticated/{bucket}/{key}", headers=_headers()
        )
    if resp.status_code >= 400:
        raise StorageError(f"download failed ({resp.status_code}): {resp.text}")
    return resp.content


def _is_not_found(resp: httpx.Response) -> bool:
    """Supabase signals a missing object inconsistently: sometimes HTTP 404, but
    for single-object DELETE it returns HTTP 400 with ``statusCode: "404"`` /
    ``error: "not_found"`` in the JSON body. Treat all of these as 'already gone'."""
    if resp.status_code == 404:
        return True
    try:
        body = resp.json()
    except Exception:
        return False
    return str(body.get("statusCode")) == "404" or body.get("error") == "not_found"


async def delete_object(key: str) -> None:
    bucket = settings.supabase_storage_bucket
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(
            f"{_base()}/object/{bucket}/{key}", headers=_headers()
        )
    # A missing object is not an error — deletion is idempotent (and callers treat
    # it as best-effort), so don't raise when it's already gone.
    if resp.status_code >= 400 and not _is_not_found(resp):
        raise StorageError(f"delete failed ({resp.status_code}): {resp.text}")
