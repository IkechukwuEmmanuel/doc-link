"""Pad access control. Phase 5.

Centralises the read/write authorization rules so REST handlers and the
WebSocket layer share one source of truth.

Rules (per PRD §5.5):
  - public_edit:  read = anyone,            write content = anyone
  - public_view:  read = anyone,            write content = owner or editor
  - private:      read = owner/collaborator, write content = owner or editor

Metadata writes (rename, visibility, archive, delete, collaborator management)
are always owner-only and are checked directly in the handlers, not here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pad import CollaboratorRole, Pad, PadCollaborator, Visibility
from app.models.user import User


def is_owner(pad: Pad, user: User | None) -> bool:
    return user is not None and pad.owner_id is not None and pad.owner_id == user.id


async def get_collaborator(
    db: AsyncSession, pad_id: uuid.UUID, user_id: uuid.UUID
) -> PadCollaborator | None:
    result = await db.execute(
        select(PadCollaborator).where(
            PadCollaborator.pad_id == pad_id, PadCollaborator.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def can_read(db: AsyncSession, pad: Pad, user: User | None) -> bool:
    if pad.visibility in (Visibility.public_edit, Visibility.public_view):
        return True
    # private: owner or any collaborator (viewer or editor)
    if is_owner(pad, user):
        return True
    if user is None:
        return False
    return await get_collaborator(db, pad.id, user.id) is not None


async def can_write_content(db: AsyncSession, pad: Pad, user: User | None) -> bool:
    if pad.visibility is Visibility.public_edit:
        return True
    # public_view / private: owner or an editor collaborator
    if is_owner(pad, user):
        return True
    if user is None:
        return False
    collab = await get_collaborator(db, pad.id, user.id)
    return collab is not None and collab.role is CollaboratorRole.editor
