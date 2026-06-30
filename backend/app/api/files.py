"""File endpoints. Access control mirrors the pad-content / WebSocket layers.

Every route enforces the *same* authorization as the rest of the app, via the
single source of truth in ``services/access.py`` plus the PIN gate in
``services/pin.py`` — no parallel permission logic lives here:

  - upload  → write permission (``can_write_content``) + PIN gate
  - list    → read permission  (``can_read``)          + PIN gate
  - download→ read permission  (``can_read``)          + PIN gate
  - delete  → write permission (owner or editor)       + PIN gate

This closes the pre-launch IDOR where any of the four routes could be hit by a
stranger on a private / PIN-protected pad with no check at all (AUDIT B5).
"""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.db.session import get_db
from app.models.file import ScanStatus
from app.models.pad import Pad
from app.models.user import User
from app.schemas.file import FileOut
from app.services import access as access_service
from app.services import file as file_service
from app.services import pad as pad_service
from app.services import pin as pin_service
from app.services import storage

router = APIRouter(prefix="/api/pads/{slug}/files", tags=["files"])


async def _require_pad(slug: str, db: AsyncSession) -> Pad:
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    return pad


async def _require_pin_access(
    db: AsyncSession, pad: Pad, user: User | None, request: Request
) -> None:
    """Enforce the PIN gate exactly as the content/WS handlers do. The owner
    bypasses it; everyone else needs a valid unlock token in the cookie."""
    unlock_token = request.cookies.get(pin_service.UNLOCK_COOKIE)
    if not await pin_service.has_pin_access(db, pad, user, unlock_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pad is locked. Enter its PIN to access its files.",
        )


async def _require_read(
    db: AsyncSession, pad: Pad, user: User | None, request: Request
) -> None:
    if not await access_service.can_read(db, pad, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pad is private. Ask the owner to share it with you.",
        )
    await _require_pin_access(db, pad, user, request)


async def _require_write(
    db: AsyncSession, pad: Pad, user: User | None, request: Request
) -> None:
    if not await access_service.can_write_content(db, pad, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this pad's files.",
        )
    await _require_pin_access(db, pad, user, request)


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    slug: str,
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    pad = await _require_pad(slug, db)
    await _require_write(db, pad, user, request)
    try:
        created = await file_service.create_file(
            db,
            pad,
            filename=file.filename or "untitled",
            content_type=file.content_type or "application/octet-stream",
            upload=file,
            user=user,
        )
    except file_service.UploadCapError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        )
    return created


@router.get("", response_model=list[FileOut])
async def list_files(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    pad = await _require_pad(slug, db)
    await _require_read(db, pad, user, request)
    return await file_service.list_files(db, pad)


@router.get("/{file_id}")
async def download_file(
    slug: str,
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    pad = await _require_pad(slug, db)
    await _require_read(db, pad, user, request)
    file = await file_service.get_file(db, pad, file_id)
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    if file.scan_status is not ScanStatus.clean:
        # Never serve anything that isn't confirmed clean.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"File is not available (scan status: {file.scan_status.value}).",
        )
    data = await storage.get_object(file.storage_key)
    return Response(
        content=data,
        media_type=file.content_type,
        headers={"Content-Disposition": f'inline; filename="{file.filename}"'},
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    slug: str,
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    pad = await _require_pad(slug, db)
    await _require_write(db, pad, user, request)
    file = await file_service.get_file(db, pad, file_id)
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    await file_service.delete_file(db, file)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
