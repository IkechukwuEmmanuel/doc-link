"""File upload orchestration: cap enforcement, storage, scanning. Phase 3."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.file import File, ScanStatus
from app.models.pad import Pad
from app.services import scan as scan_service
from app.services import storage

settings = get_settings()


class UploadCapError(Exception):
    """Raised when an upload would exceed a pad's quota."""


def _caps() -> tuple[int, int, int]:
    # Anonymous caps for now; auth-tier caps land with Phase 4.
    return (
        settings.anon_max_files_per_pad,
        settings.anon_max_file_bytes,
        settings.anon_max_total_bytes,
    )


async def list_files(db: AsyncSession, pad: Pad) -> list[File]:
    result = await db.execute(
        select(File).where(File.pad_id == pad.id).order_by(File.created_at)
    )
    return list(result.scalars().all())


async def get_file(db: AsyncSession, pad: Pad, file_id: uuid.UUID) -> File | None:
    result = await db.execute(
        select(File).where(File.id == file_id, File.pad_id == pad.id)
    )
    return result.scalar_one_or_none()


async def _enforce_caps(db: AsyncSession, pad: Pad, size: int) -> None:
    max_files, max_file_bytes, max_total_bytes = _caps()
    if size > max_file_bytes:
        raise UploadCapError(
            f"File exceeds the {max_file_bytes} byte per-file limit."
        )
    agg = await db.execute(
        select(func.count(File.id), func.coalesce(func.sum(File.size_bytes), 0)).where(
            File.pad_id == pad.id
        )
    )
    count, total = agg.one()
    if count + 1 > max_files:
        raise UploadCapError(f"This pad already has the maximum of {max_files} files.")
    if total + size > max_total_bytes:
        raise UploadCapError(
            f"Upload would exceed the {max_total_bytes} byte total limit for this pad."
        )


async def create_file(
    db: AsyncSession,
    pad: Pad,
    *,
    filename: str,
    content_type: str,
    data: bytes,
) -> File:
    """Validate caps, store the bytes, scan, and persist the resulting status.

    If the scan does not return clean, the object is deleted from storage and the
    row is kept with ``failed`` status so the file is never served.
    """
    await _enforce_caps(db, pad, len(data))

    storage_key = f"{pad.id}/{uuid.uuid4()}"
    await storage.put_object(storage_key, data, content_type)

    file = File(
        pad_id=pad.id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        storage_key=storage_key,
        scan_status=ScanStatus.pending,
    )
    db.add(file)
    await db.commit()
    await db.refresh(file)

    status = await scan_service.scan(data)
    file.scan_status = status
    if status is not ScanStatus.clean:
        await storage.delete_object(storage_key)
    await db.commit()
    await db.refresh(file)
    return file


async def delete_file(db: AsyncSession, file: File) -> None:
    # Best-effort storage removal (object may already be gone if the scan failed).
    try:
        await storage.delete_object(file.storage_key)
    except Exception:
        pass
    await db.delete(file)
    await db.commit()
