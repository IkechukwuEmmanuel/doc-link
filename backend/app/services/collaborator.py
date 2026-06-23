"""Collaborator management. Phase 5.

v1 access control is intentionally simple (PRD §5.5): inviting an *existing*
user creates the collaborator row immediately (accepted on creation, no separate
accept step). Inviting an email with no matching account is out of scope and
surfaced to the caller as a distinct error.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pad import CollaboratorRole, PadCollaborator
from app.models.user import User


class NoSuchUserError(Exception):
    """Raised when inviting an email that has no registered account (out of scope v1)."""


class CannotInviteOwnerError(Exception):
    """Raised when the invited email belongs to the pad owner."""


async def list_collaborators(
    db: AsyncSession, pad_id: uuid.UUID
) -> list[tuple[PadCollaborator, User]]:
    result = await db.execute(
        select(PadCollaborator, User)
        .join(User, User.id == PadCollaborator.user_id)
        .where(PadCollaborator.pad_id == pad_id)
        .order_by(PadCollaborator.invited_at)
    )
    return [(row[0], row[1]) for row in result.all()]


async def add_collaborator(
    db: AsyncSession,
    *,
    pad_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    email: str,
    role: CollaboratorRole,
) -> tuple[PadCollaborator, User]:
    normalized = email.strip().lower()
    user = (
        await db.execute(select(User).where(User.email == normalized))
    ).scalar_one_or_none()
    if user is None:
        raise NoSuchUserError(normalized)
    if owner_id is not None and user.id == owner_id:
        raise CannotInviteOwnerError(normalized)

    existing = (
        await db.execute(
            select(PadCollaborator).where(
                PadCollaborator.pad_id == pad_id,
                PadCollaborator.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Idempotent role update rather than a duplicate-key error.
        existing.role = role
        if existing.accepted_at is None:
            existing.accepted_at = func.now()
        await db.commit()
        await db.refresh(existing)
        return existing, user

    collab = PadCollaborator(
        pad_id=pad_id,
        user_id=user.id,
        role=role,
        accepted_at=func.now(),  # no separate accept step in v1
    )
    db.add(collab)
    await db.commit()
    await db.refresh(collab)
    return collab, user


async def remove_collaborator(
    db: AsyncSession, *, pad_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    collab = (
        await db.execute(
            select(PadCollaborator).where(
                PadCollaborator.pad_id == pad_id,
                PadCollaborator.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if collab is None:
        return False
    await db.delete(collab)
    await db.commit()
    return True
