import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.file import ScanStatus
from app.schemas.file import FileOut
from app.services import file as file_service
from app.services import pad as pad_service
from app.services import storage

router = APIRouter(prefix="/api/pads/{slug}/files", tags=["files"])


async def _require_pad(slug: str, db: AsyncSession):
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    return pad


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(slug: str, file: UploadFile, db: AsyncSession = Depends(get_db)):
    pad = await _require_pad(slug, db)
    data = await file.read()
    try:
        created = await file_service.create_file(
            db,
            pad,
            filename=file.filename or "untitled",
            content_type=file.content_type or "application/octet-stream",
            data=data,
        )
    except file_service.UploadCapError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        )
    return created


@router.get("", response_model=list[FileOut])
async def list_files(slug: str, db: AsyncSession = Depends(get_db)):
    pad = await _require_pad(slug, db)
    return await file_service.list_files(db, pad)


@router.get("/{file_id}")
async def download_file(slug: str, file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    pad = await _require_pad(slug, db)
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
async def delete_file(slug: str, file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    pad = await _require_pad(slug, db)
    file = await file_service.get_file(db, pad, file_id)
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    await file_service.delete_file(db, file)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
