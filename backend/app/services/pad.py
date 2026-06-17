import random

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pad import Pad
from app.services import slug as slug_service

_MAX_GENERATION_ATTEMPTS = 25


class SlugTakenError(Exception):
    """Raised when a requested slug already exists."""


async def get_pad_by_slug(db: AsyncSession, slug: str) -> Pad | None:
    result = await db.execute(select(Pad).where(Pad.slug == slug))
    return result.scalar_one_or_none()


async def touch_last_opened(db: AsyncSession, pad: Pad) -> None:
    pad.last_opened_at = func.now()
    await db.commit()
    await db.refresh(pad)


async def _generate_unique_slug(db: AsyncSession, rng: random.Random | None = None) -> str:
    for _ in range(_MAX_GENERATION_ATTEMPTS):
        candidate = slug_service.generate_slug(rng)
        existing = await get_pad_by_slug(db, candidate)
        if existing is None:
            return candidate
    # Extremely unlikely; widen entropy with a longer numeric suffix.
    base = slug_service.generate_slug(rng)
    return f"{base}-{random.randint(100, 9999)}"


async def create_pad(
    db: AsyncSession,
    *,
    slug: str | None,
    content: str = "",
    rng: random.Random | None = None,
) -> Pad:
    """Create a pad. If slug is None, auto-generate. Validates custom slugs.

    Raises slug_service.SlugError on invalid custom slug, SlugTakenError on collision.
    """
    if slug is None:
        final_slug = await _generate_unique_slug(db, rng)
    else:
        final_slug = slug_service.validate_custom_slug(slug)
        if await get_pad_by_slug(db, final_slug) is not None:
            raise SlugTakenError(final_slug)

    pad = Pad(slug=final_slug, content=content, owner_id=None, is_anonymous=True)
    db.add(pad)
    try:
        await db.commit()
    except IntegrityError:
        # Race: another request inserted the same slug between check and commit.
        await db.rollback()
        raise SlugTakenError(final_slug)
    await db.refresh(pad)
    return pad


async def update_pad_content(db: AsyncSession, pad: Pad, content: str) -> Pad:
    pad.content = content
    await db.commit()
    await db.refresh(pad)
    return pad


class PadAlreadyOwnedError(Exception):
    """Raised when claiming a pad that already has an owner."""


async def claim_pad(db: AsyncSession, pad: Pad, owner_id) -> Pad:
    if pad.owner_id is not None:
        raise PadAlreadyOwnedError(pad.slug)
    pad.owner_id = owner_id
    pad.is_anonymous = False
    await db.commit()
    await db.refresh(pad)
    return pad
