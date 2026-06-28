"""Supabase profile mirroring (AUDIT H2).

Covers: the chosen username is used (not derived from the email), and a username
collision between two different auth users is resolved with a unique suffix
instead of returning None / 500ing the caller.
"""

import uuid

from app.services import user as user_service


async def test_chosen_username_is_used_not_email_localpart(session_factory):
    async with session_factory() as db:
        u = await user_service.upsert_profile(
            db,
            user_id=uuid.uuid4(),
            email="someone@example.com",
            username="cooldev",
        )
        assert u is not None
        assert u.username == "cooldev"  # not "someone"


async def test_username_collision_gets_unique_suffix(session_factory):
    async with session_factory() as db:
        first = await user_service.upsert_profile(
            db, user_id=uuid.uuid4(), email="john@a.com", username="john"
        )
        second = await user_service.upsert_profile(
            db, user_id=uuid.uuid4(), email="john@b.com", username="john"
        )
        assert first is not None and second is not None
        assert first.username == "john"
        # Distinct user, same chosen username → suffixed, never None, never a 500.
        assert second.username != "john"
        assert second.username.startswith("john-")


async def test_derived_username_collision_also_suffixed(session_factory):
    """Even without a chosen username (legacy/OAuth), the email-local-part
    fallback must not collide-and-crash."""
    async with session_factory() as db:
        first = await user_service.upsert_profile(
            db, user_id=uuid.uuid4(), email="dev@a.com"
        )
        second = await user_service.upsert_profile(
            db, user_id=uuid.uuid4(), email="dev@b.com"
        )
        assert first.username == "dev"
        assert second.username != "dev" and second.username.startswith("dev-")


async def test_email_localpart_sanitized_to_valid_username(session_factory):
    async with session_factory() as db:
        u = await user_service.upsert_profile(
            db, user_id=uuid.uuid4(), email="a.b+tag@example.com"
        )
        # Dots/plus are not allowed in usernames → coerced to hyphens, collapsed.
        assert u.username == "a-b-tag"
