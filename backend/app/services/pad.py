import random
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.pad import Pad, PadCollaborator, Visibility
from app.services import slug as slug_service
from app.services import storage

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
    owner_id: uuid.UUID | None = None,
    rng: random.Random | None = None,
) -> Pad:
    """Create a pad. If slug is None, auto-generate. Validates custom slugs.

    When ``owner_id`` is given (authenticated creation, e.g. from the dashboard)
    the pad is owned and non-anonymous from the start — no separate claim step.

    Raises slug_service.SlugError on invalid custom slug, SlugTakenError on collision.
    """
    if slug is None:
        final_slug = await _generate_unique_slug(db, rng)
    else:
        final_slug = slug_service.validate_custom_slug(slug)
        if await get_pad_by_slug(db, final_slug) is not None:
            raise SlugTakenError(final_slug)

    pad = Pad(
        slug=final_slug,
        content=content,
        owner_id=owner_id,
        is_anonymous=owner_id is None,
    )
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


_UNSET = object()


async def update_pad_metadata(
    db: AsyncSession,
    pad: Pad,
    *,
    name=_UNSET,
    visibility: Visibility | None = _UNSET,
    is_archived: bool | None = _UNSET,
) -> Pad:
    """Owner-only partial metadata update (rename / visibility / archive).

    Only fields explicitly passed (not ``_UNSET``) are applied, so ``name=None``
    clears the custom name while an omitted ``name`` leaves it untouched.
    """
    if name is not _UNSET:
        pad.name = name
    if visibility is not _UNSET and visibility is not None:
        pad.visibility = visibility
    if is_archived is not _UNSET and is_archived is not None:
        pad.is_archived = is_archived
    await db.commit()
    await db.refresh(pad)
    return pad


async def delete_pad(db: AsyncSession, pad: Pad) -> None:
    """Hard-delete a pad: remove file objects from storage, then DB rows.

    Collaborator and file rows are removed explicitly (rather than relying on DB
    FK cascade) so the behaviour is identical across Postgres and the SQLite test
    harness, and so storage objects are never orphaned.
    """
    files = (
        await db.execute(select(File).where(File.pad_id == pad.id))
    ).scalars().all()
    for f in files:
        try:
            await storage.delete_object(f.storage_key)
        except Exception:
            # Object may already be gone (e.g. scan-failed uploads); not fatal.
            pass
        await db.delete(f)
    collabs = (
        await db.execute(
            select(PadCollaborator).where(PadCollaborator.pad_id == pad.id)
        )
    ).scalars().all()
    for c in collabs:
        await db.delete(c)
    await db.delete(pad)
    await db.commit()


async def list_owned_pads(
    db: AsyncSession,
    owner_id: uuid.UUID,
    *,
    archived: bool = False,
    q: str | None = None,
) -> list[dict]:
    """Owned pads for the dashboard, newest-opened first, with file aggregates.

    Returns plain dicts (pad + file_count + size_bytes) so the route can build
    ``PadListItem`` without a second round-trip per pad.
    """
    stmt = (
        select(
            Pad,
            func.count(File.id).label("file_count"),
            func.coalesce(func.sum(File.size_bytes), 0).label("size_bytes"),
        )
        .outerjoin(File, File.pad_id == Pad.id)
        .where(Pad.owner_id == owner_id, Pad.is_archived == archived)
        .group_by(Pad.id)
        .order_by(Pad.last_opened_at.desc())
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Pad.name.ilike(like), Pad.slug.ilike(like)))
    result = await db.execute(stmt)
    items = []
    for pad, file_count, size_bytes in result.all():
        items.append({"pad": pad, "file_count": file_count, "size_bytes": size_bytes})
    return items
