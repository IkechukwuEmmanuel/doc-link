"""User creation and lookup. Phase 4."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import auth as auth_service
from app.services import username as username_service


class EmailTakenError(Exception):
    """Raised when an email is already registered."""


class UsernameTakenError(Exception):
    """Raised when a username is already taken."""


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    normalized = email.strip().lower()
    return (
        await db.execute(select(User).where(User.email == normalized))
    ).scalar_one_or_none()


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    normalized = username.strip().lower()
    return (
        await db.execute(select(User).where(User.username == normalized))
    ).scalar_one_or_none()


async def upsert_profile(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | str,
    email: str,
    display_name: str | None = None,
    email_verified: bool = False,
    provider: str | None = None,
    username: str | None = None,
) -> User:
    """Create or refresh the ``public.users`` profile mirroring an
    ``auth.users`` row (same UUID). The linkage is matching-UUID
    (``public.users.id == auth.users.id``), enforced in application code — see
    DECISIONS.md for why we don't add a cross-schema DB foreign key.
    """
    uid = uuid.UUID(str(user_id))
    normalized = email.strip().lower()
    
    # Generate a default username if not provided (for OAuth/Supabase sign-ins)
    if username is None:
        username = normalized.split("@")[0]
        # Ensure minimum length of 3 for username
        if len(username) < 3:
            username = username + "user"
    
    user = await get_by_id(db, uid)
    if user is None:
        user = User(
            id=uid,
            email=normalized,
            display_name=display_name,
            email_verified=email_verified,
            oauth_provider=provider,
            username=username,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return await get_by_id(db, uid)
        await db.refresh(user)
        return user

    changed = False
    if normalized and user.email != normalized:
        user.email = normalized
        changed = True
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        changed = True
    if provider and user.oauth_provider != provider:
        user.oauth_provider = provider
        changed = True
    # Only ever upgrade verification — never silently downgrade it.
    if email_verified and not user.email_verified:
        user.email_verified = True
        changed = True
    if changed:
        await db.commit()
        await db.refresh(user)
    return user


async def get_or_sync_from_claims(
    db: AsyncSession, claims: dict, *, mark_verified: bool
) -> User | None:
    """Resolve the profile for a verified access token, syncing it from the
    token claims. Returns None for a token whose ``sub`` has no profile and whose
    claims carry no email to bootstrap one (the legacy/test path)."""
    sub = claims.get("sub")
    if not sub:
        return None
    try:
        uid = uuid.UUID(str(sub))
    except (ValueError, TypeError):
        return None

    email = (claims.get("email") or "").strip().lower()
    meta = claims.get("user_metadata") or {}
    display_name = meta.get("display_name") or meta.get("full_name") or meta.get("name")
    provider = (claims.get("app_metadata") or {}).get("provider")

    if not email:
        # Legacy/offline token (sub only): only resolve an existing profile.
        existing = await get_by_id(db, uid)
        if existing is not None and mark_verified and not existing.email_verified:
            existing.email_verified = True
            await db.commit()
            await db.refresh(existing)
        return existing

    return await upsert_profile(
        db,
        user_id=uid,
        email=email,
        display_name=display_name,
        email_verified=mark_verified,
        provider=provider,
    )


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    username: str,
    password: str,
    display_name: str | None = None,
) -> User:
    # Validate and normalize username
    try:
        normalized_username = username_service.validate_username(username)
    except username_service.UsernameError as e:
        raise UsernameTakenError(str(e))
    
    user = User(
        email=email.strip().lower(),
        username=normalized_username,
        password_hash=auth_service.hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        if "email" in str(e):
            raise EmailTakenError(email)
        elif "username" in str(e):
            raise UsernameTakenError(username)
        raise
    await db.refresh(user)
    return user


async def set_password(db: AsyncSession, user: User, new_password: str) -> User:
    user.password_hash = auth_service.hash_password(new_password)
    await db.commit()
    await db.refresh(user)
    return user


async def mark_email_verified(db: AsyncSession, user: User) -> User:
    user.email_verified = True
    await db.commit()
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

    # Generate a default username based on email
    normalized_email = email.strip().lower()
    username = normalized_email.split("@")[0]
    # Ensure minimum length of 3 for username
    if len(username) < 3:
        username = username + "user"
    
    user = User(
        email=normalized_email,
        oauth_provider="google",
        oauth_subject=subject,
        email_verified=True,
        display_name=display_name,
        username=username,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await get_by_email(db, email)
    await db.refresh(user)
    return user
