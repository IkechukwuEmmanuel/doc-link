"""Pad naming, redirects, and namespaced uniqueness.

Adapts the spec's redirect/namespace model onto the existing schema (Path A):
the pad's immutable ``slug`` is left untouched (global-unique, AUDIT B3/B4); the
mutable ``name`` is the canonical display name; historical names live in the
``redirects`` table (replacing the old ``previous_names`` JSON column).

Two namespaces, exactly as the spec describes:

* **anonymous** — one flat pool. A name is taken if *any* pad uses it as a slug
  (slugs resolve at the bare ``/{a}`` route, so they share this pool), if any
  anonymous pad uses it as a ``name``, or if an active anonymous redirect points
  from it.
* **claimed** — scoped per owner. Taken only within that owner's pads/redirects.

Resolution is never an HTTP 301 (AUDIT B4): callers resolve an old name to the
live pad and return it (200) with ``canonical_url`` so the SPA fixes the address
bar itself.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pad import Pad, Redirect
from app.models.user import User

ANONYMOUS = "anonymous"
CLAIMED = "claimed"


def namespace_of(pad: Pad) -> tuple[str, uuid.UUID | None]:
    """The (namespace, namespace_owner) pair a pad's names live in."""
    if pad.owner_id is None:
        return ANONYMOUS, None
    return CLAIMED, pad.owner_id


async def canonical_url_for(db: AsyncSession, pad: Pad) -> str | None:
    """Current canonical browser URL for a pad.

    * owned → ``/{username}/{name or slug}``
    * anonymous + renamed → ``/{name}``
    * anonymous + never renamed → ``None`` (the bar is already at ``/{slug}``)
    """
    if pad.owner_id is not None:
        owner = (
            await db.execute(select(User).where(User.id == pad.owner_id))
        ).scalar_one_or_none()
        if owner is None:
            return None
        return f"/{owner.username}/{pad.name or pad.slug}"
    if pad.name:
        return f"/{pad.name}"
    return None


async def _redirect_target(db: AsyncSession, pad: Pad) -> str:
    """Like canonical_url_for but always a concrete string (anonymous pads with
    no custom name fall back to ``/{slug}``) — redirect rows must point somewhere."""
    url = await canonical_url_for(db, pad)
    return url if url is not None else f"/{pad.slug}"


async def is_name_available(
    db: AsyncSession,
    candidate: str,
    *,
    namespace: str,
    namespace_owner: uuid.UUID | None,
    exclude_pad_id: uuid.UUID | None = None,
) -> bool:
    """Fast-path UX pre-check (the DB unique index is the real backstop).

    A name is free only if no live pad uses it AND no *active* redirect points
    from it, within the given namespace.
    """
    # 1) Live pad using this name as a slug or custom name.
    if namespace == ANONYMOUS:
        # Slugs are global and resolve at the bare route → share the anon pool.
        slug_q = select(Pad.id).where(Pad.slug == candidate)
        name_q = select(Pad.id).where(Pad.owner_id.is_(None), Pad.name == candidate)
    else:
        slug_q = select(Pad.id).where(
            Pad.owner_id == namespace_owner, Pad.slug == candidate
        )
        name_q = select(Pad.id).where(
            Pad.owner_id == namespace_owner, Pad.name == candidate
        )
    if exclude_pad_id is not None:
        slug_q = slug_q.where(Pad.id != exclude_pad_id)
        name_q = name_q.where(Pad.id != exclude_pad_id)
    if (await db.execute(slug_q)).first() is not None:
        return False
    if (await db.execute(name_q)).first() is not None:
        return False

    # 2) Active redirect pointing from this name in the namespace.
    red_q = select(Redirect.id).where(
        Redirect.active.is_(True),
        Redirect.namespace == namespace,
        Redirect.old_slug == candidate,
    )
    if namespace == CLAIMED:
        red_q = red_q.where(Redirect.namespace_owner == namespace_owner)
    if exclude_pad_id is not None:
        red_q = red_q.where(Redirect.pad_id != exclude_pad_id)
    if (await db.execute(red_q)).first() is not None:
        return False
    return True


async def resolve_redirect(
    db: AsyncSession,
    segment: str,
    *,
    namespace: str,
    namespace_owner: uuid.UUID | None = None,
) -> Pad | None:
    """Resolve a historical name to its pad via an active redirect, or None."""
    q = select(Pad).join(Redirect, Redirect.pad_id == Pad.id).where(
        Redirect.active.is_(True),
        Redirect.namespace == namespace,
        Redirect.old_slug == segment,
    )
    if namespace == CLAIMED:
        q = q.where(Redirect.namespace_owner == namespace_owner)
    return (await db.execute(q)).scalars().first()


async def record_name_change(
    db: AsyncSession,
    pad: Pad,
    *,
    old_name: str | None,
    old_namespace: str,
    old_namespace_owner: uuid.UUID | None,
) -> None:
    """Maintain the redirect trail after a rename/claim. Caller commits.

    ``old_name`` is recorded in the namespace it *used to* live in
    (``old_namespace``/``old_namespace_owner``) — on a claim that is the
    *anonymous* namespace even though the pad is now claimed, so the old anonymous
    URL keeps resolving to the new ``/{username}/...`` address.

    1. Point *every* existing active redirect for this pad at the new canonical
       URL (never chain — the spec's "always point at current canonical").
    2. If there's an old name to preserve, upsert one redirect from it.
    3. Deactivate any redirect whose ``old_slug`` equals the *new* canonical name
       (re-taking a previously-freed name → it's canonical again, not a redirect).
    """
    target = await _redirect_target(db, pad)
    new_namespace, new_owner = namespace_of(pad)
    new_canonical_name = pad.name or pad.slug

    existing = (
        await db.execute(select(Redirect).where(Redirect.pad_id == pad.id))
    ).scalars().all()
    for r in existing:
        if r.active:
            r.target_url = target

    # Skip only when the *full address* is unchanged (same name AND namespace) —
    # a claim keeps the name but moves anonymous→claimed, so it still needs a
    # redirect from the old anonymous address.
    same_address = (
        old_name == new_canonical_name
        and old_namespace == new_namespace
        and old_namespace_owner == new_owner
    )
    if old_name and not same_address:
        # Reactivate a matching dormant row if present, else insert a new one.
        reused = next(
            (
                r
                for r in existing
                if r.old_slug == old_name
                and r.namespace == old_namespace
                and r.namespace_owner == old_namespace_owner
            ),
            None,
        )
        if reused is not None:
            reused.active = True
            reused.target_url = target
        else:
            db.add(
                Redirect(
                    pad_id=pad.id,
                    old_slug=old_name,
                    namespace=old_namespace,
                    namespace_owner=old_namespace_owner,
                    target_url=target,
                )
            )

    # A redirect FROM the now-canonical *address* would shadow the live pad —
    # retire it (re-taking a previously-freed name within the same namespace).
    for r in existing:
        if (
            r.active
            and r.old_slug == new_canonical_name
            and r.namespace == new_namespace
            and r.namespace_owner == new_owner
        ):
            r.active = False


async def list_for_pad(db: AsyncSession, pad_id: uuid.UUID) -> list[Redirect]:
    """Active redirects pointing at a pad (for the 'manage old links' view)."""
    return list(
        (
            await db.execute(
                select(Redirect)
                .where(Redirect.pad_id == pad_id, Redirect.active.is_(True))
                .order_by(Redirect.created_at.desc())
            )
        ).scalars()
    )


async def kill_redirect(
    db: AsyncSession, *, redirect_id: uuid.UUID, pad_id: uuid.UUID
) -> bool:
    """Deactivate one redirect (scoped to its pad for authz). Frees the name.

    Single-row, no cascade: the "always point at current canonical" design means
    no other redirect ever depended on this one. Returns True if one was killed.
    """
    row = (
        await db.execute(
            select(Redirect).where(
                Redirect.id == redirect_id,
                Redirect.pad_id == pad_id,
                Redirect.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.active = False
    await db.commit()
    return True
