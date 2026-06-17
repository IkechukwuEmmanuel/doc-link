"""User creation and lookup. Phase 4."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import auth as auth_service


class EmailTakenError(Exception):
    """Raised when an email is already registered."""


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    normalized = email.strip().lower()
    return (
        await db.execute(select(User).where(User.email == normalized))
    ).scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    user = User(
        email=email.strip().lower(),
        password_hash=auth_service.hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise EmailTakenError(email)
    await db.refresh(user)
    return user


async def upsert_google_user(
    db: AsyncSession,
    *,
    email: str,
    subject: str,
    display_name: str | None,
) -> User:
    """Find or create a user from a verified Google profile."""
    existing = await get_by_email(db, email)
    if existing is not None:
        if existing.oauth_provider is None:
            existing.oauth_provider = "google"
            existing.oauth_subject = subject
            existing.email_verified = True
            await db.commit()
            await db.refresh(existing)
        return existing

    user = User(
        email=email.strip().lower(),
        oauth_provider="google",
        oauth_subject=subject,
        email_verified=True,
        display_name=display_name,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await get_by_email(db, email)
    await db.refresh(user)
    return user
