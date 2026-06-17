from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.pad import PadCreate, PadOut, PadUpdate
from app.services import pad as pad_service
from app.services import slug as slug_service

router = APIRouter(prefix="/api/pads", tags=["pads"])


@router.post("", response_model=PadOut, status_code=status.HTTP_201_CREATED)
async def create_pad(body: PadCreate, db: AsyncSession = Depends(get_db)):
    """Create a pad. Empty body → anonymous pad with an auto-generated slug."""
    try:
        pad = await pad_service.create_pad(db, slug=body.slug, content=body.content)
    except slug_service.SlugError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except pad_service.SlugTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already taken."
        )
    return pad


@router.get("/{slug}", response_model=PadOut)
async def get_pad(slug: str, db: AsyncSession = Depends(get_db)):
    """Fetch a pad by slug. 404 with creatable flag if it's a valid-but-unused slug."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        creatable = True
        try:
            slug_service.validate_custom_slug(slug)
        except slug_service.SlugError:
            creatable = False
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "This pad doesn't exist yet.", "creatable": creatable},
        )
    await pad_service.touch_last_opened(db, pad)
    return pad


@router.put("/{slug}", response_model=PadOut)
async def update_pad(slug: str, body: PadUpdate, db: AsyncSession = Depends(get_db)):
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    pad = await pad_service.update_pad_content(db, pad, body.content)
    return pad


@router.post("/{slug}/claim", response_model=PadOut)
async def claim_pad(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Claim ownership of an anonymous, unowned pad (requires auth)."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    try:
        pad = await pad_service.claim_pad(db, pad, user.id)
    except pad_service.PadAlreadyOwnedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This pad already has an owner."
        )
    return pad


@router.get("/{slug}/raw")
async def get_pad_raw(slug: str, db: AsyncSession = Depends(get_db)):
    """Raw markdown/text export — no editor chrome, suitable for curl (PRD §4)."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    return Response(content=pad.content, media_type="text/plain; charset=utf-8")
