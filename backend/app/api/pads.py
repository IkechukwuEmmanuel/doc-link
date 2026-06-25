import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.db.session import get_db
from app.models.pad import Pad, PinFormat, Visibility
from app.models.user import User
from app.schemas.pad import (
    CollaboratorIn,
    CollaboratorOut,
    PadCreate,
    PadListItem,
    PadOut,
    PadPatch,
    PadUpdate,
    PinUnlockIn,
)
from app.services import access as access_service
from app.services import collaborator as collab_service
from app.services import pad as pad_service
from app.services import pin as pin_service
from app.services import ratelimit as ratelimit_service
from app.services import slug as slug_service
from app.services import user as user_service

router = APIRouter(prefix="/api/pads", tags=["pads"])


async def _pad_out(
    db: AsyncSession, pad: Pad, user: User | None, unlock_token: str | None = None
) -> PadOut:
    out = PadOut.model_validate(pad)
    if not await pin_service.has_pin_access(db, pad, user, unlock_token):
        # Withhold content from a locked pad; the frontend renders the PIN screen.
        out.locked = True
        out.content = ""
        out.can_edit = False
        return out
    out.can_edit = await access_service.can_write_content(db, pad, user)
    return out


def _require_owner(pad: Pad, user: User) -> None:
    if not access_service.is_owner(pad, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the pad owner can do that.",
        )


@router.get("", response_model=list[PadListItem])
async def list_my_pads(
    archived: bool = False,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List the current user's owned pads (dashboard). Newest-opened first."""
    rows = await pad_service.list_owned_pads(db, user.id, archived=archived, q=q)
    out: list[PadListItem] = []
    for r in rows:
        pad = r["pad"]
        out.append(
            PadListItem(
                id=pad.id,
                slug=pad.slug,
                name=pad.name,
                visibility=pad.visibility,
                is_archived=pad.is_archived,
                pin_protected=pad.pin_protected,
                last_opened_at=pad.last_opened_at,
                created_at=pad.created_at,
                updated_at=pad.updated_at,
                file_count=r["file_count"],
                size_bytes=r["size_bytes"],
            )
        )
    return out


@router.post("", response_model=PadOut, status_code=status.HTTP_201_CREATED)
async def create_pad(
    body: PadCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Create a pad. Empty body → anonymous pad with an auto-generated slug.

    Authenticated callers (dashboard "New Pad") own the pad at creation time, so
    no separate claim step is needed. Anonymous creation is rate-limited by IP.
    """
    if user is None:
        retry_after = await ratelimit_service.check_pad_creation(request)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="You're creating pads too quickly. Please wait a moment and try again.",
                headers={"Retry-After": str(retry_after)},
            )
    try:
        pad = await pad_service.create_pad(
            db,
            slug=body.slug,
            content=body.content,
            owner_id=user.id if user else None,
        )
    except slug_service.SlugError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except pad_service.SlugTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already taken."
        )
    return await _pad_out(db, pad, user)


@router.get("/{username}/{padname}")
async def get_owned_pad(
    username: str,
    padname: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Fetch a pad owned by a user, by username and padname.
    
    The padname can be either the slug or a custom name. If the padname is a
    previous custom name (the pad was renamed), redirect to the current name.
    """
    from app.models.user import User as UserModel
    
    # Look up the owner by username
    owner = await db.execute(
        select(UserModel).where(UserModel.username == username.lower())
    )
    owner_user = owner.scalar_one_or_none()
    if owner_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found.", "creatable": False},
        )
    
    # Look up the pad by owner_id and padname
    from sqlalchemy import or_
    result = await db.execute(
        select(Pad).where(
            (Pad.owner_id == owner_user.id) &
            ((Pad.slug == padname) | (Pad.name == padname))
        )
    )
    pad = result.scalar_one_or_none()
    
    if pad is None:
        # Check if the padname is a previous name; if so, redirect to the current name
        result = await db.execute(
            select(Pad).where(
                (Pad.owner_id == owner_user.id) &
                (Pad.previous_names.contains([padname]))
            )
        )
        pad = result.scalar_one_or_none()
        if pad:
            # Redirect to the current pad name
            new_url = f"/api/pads/{username}/{pad.name or pad.slug}"
            return RedirectResponse(url=new_url, status_code=status.HTTP_301_MOVED_PERMANENTLY)
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "This pad doesn't exist yet.", "creatable": False},
        )
    
    if not await access_service.can_read(db, pad, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pad is private. Ask the owner to share it with you.",
        )
    await pad_service.touch_last_opened(db, pad)
    unlock_token = request.cookies.get(pin_service.UNLOCK_COOKIE)
    return await _pad_out(db, pad, user, unlock_token)


@router.get("/{slug}")
async def get_pad(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Fetch a pad by slug. 404 with creatable flag if it's a valid-but-unused slug.

    Private pads are 403 to anyone who is not the owner or a collaborator. A
    PIN-protected pad returns 200 with ``locked: true`` and no content until the
    requester presents a valid unlock token (the existence is never hidden).
    
    If the pad has been claimed (has an owner), redirect to /{username}/{slug}.
    """
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
    
    # Check visibility first, before redirect
    if not await access_service.can_read(db, pad, user):
        # 403 (not 404): a private pad is "unlisted", its existence isn't secret.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pad is private. Ask the owner to share it with you.",
        )
    
    # If the pad has an owner, redirect to the new address
    if pad.owner_id is not None:
        owner = await user_service.get_by_id(db, pad.owner_id)
        if owner:
            new_url = f"/api/pads/{owner.username}/{pad.name or pad.slug}"
            return RedirectResponse(url=new_url, status_code=status.HTTP_301_MOVED_PERMANENTLY)
    
    await pad_service.touch_last_opened(db, pad)
    unlock_token = request.cookies.get(pin_service.UNLOCK_COOKIE)
    return await _pad_out(db, pad, user, unlock_token)


@router.put("/{slug}", response_model=PadOut)
async def update_pad(
    slug: str,
    body: PadUpdate,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Content (body) save fallback. Honours the same write rules as the live WS."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    if not await access_service.can_write_content(db, pad, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this pad.",
        )
    pad = await pad_service.update_pad_content(db, pad, body.content)
    return await _pad_out(db, pad, user)


@router.patch("/{slug}", response_model=PadOut)
async def patch_pad(
    slug: str,
    body: PadPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Owner-only metadata update: rename, visibility, archive/unarchive, PIN."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    _require_owner(pad, user)
    fields = body.model_dump(exclude_unset=True)

    # PRD §5.6: a pad can only be made private by a verified account.
    if body.visibility is Visibility.private and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email address before making a pad private.",
        )

    # PIN protection is orthogonal to visibility but mutually exclusive with
    # `private` (private already requires an account — a strictly stronger gate).
    effective_visibility = fields.get("visibility", pad.visibility)
    effective_pin = fields.get("pin_protected", pad.pin_protected)
    if effective_visibility is Visibility.private and effective_pin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A private pad can't also be PIN-protected — private is a stronger gate.",
        )

    pad = await pad_service.update_pad_metadata(
        db,
        pad,
        name=fields["name"] if "name" in fields else pad_service._UNSET,
        visibility=fields.get("visibility", pad_service._UNSET),
        is_archived=fields.get("is_archived", pad_service._UNSET),
    )

    if "pin_protected" in fields:
        if body.pin_protected:
            if not body.pin:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="A PIN is required to enable PIN protection.",
                )
            pin_format = body.pin_format or PinFormat.numeric
            try:
                pad = await pin_service.set_pin(
                    db, pad, pin=body.pin, pin_format=pin_format
                )
            except pin_service.InvalidPinError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
                )
        else:
            pad = await pin_service.clear_pin(db, pad)

    return await _pad_out(db, pad, user)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pad(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Owner-only hard delete (cascades to files + collaborators + storage)."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    _require_owner(pad, user)
    await pad_service.delete_pad(db, pad)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    return await _pad_out(db, pad, user)


@router.get("/{slug}/collaborators", response_model=list[CollaboratorOut])
async def list_collaborators(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    _require_owner(pad, user)
    rows = await collab_service.list_collaborators(db, pad.id)
    return [
        CollaboratorOut(
            user_id=c.user_id,
            email=u.email,
            display_name=u.display_name,
            role=c.role,
            invited_at=c.invited_at,
            accepted_at=c.accepted_at,
        )
        for c, u in rows
    ]


@router.post(
    "/{slug}/collaborators",
    response_model=CollaboratorOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_collaborator(
    slug: str,
    body: CollaboratorIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    _require_owner(pad, user)
    try:
        collab, invited = await collab_service.add_collaborator(
            db, pad_id=pad.id, owner_id=pad.owner_id, email=body.email, role=body.role
        )
    except collab_service.NoSuchUserError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No account exists for that email. Inviting new users isn't supported yet.",
        )
    except collab_service.CannotInviteOwnerError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="You already own this pad.",
        )
    return CollaboratorOut(
        user_id=collab.user_id,
        email=invited.email,
        display_name=invited.display_name,
        role=collab.role,
        invited_at=collab.invited_at,
        accepted_at=collab.accepted_at,
    )


@router.delete(
    "/{slug}/collaborators/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_collaborator(
    slug: str,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    _require_owner(pad, user)
    removed = await collab_service.remove_collaborator(
        db, pad_id=pad.id, user_id=user_id
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collaborator not found."
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{slug}/unlock", response_model=PadOut)
async def unlock_pad(
    slug: str,
    body: PinUnlockIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Submit a PIN to unlock a PIN-protected pad for the session window.

    Strictly rate-limited per pad per IP (brute-force defense). A wrong PIN
    (401) is a distinct error from being rate-limited (429) so the frontend can
    render each correctly.
    """
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    if not pad.pin_protected:
        # Nothing to unlock — return the pad as normal.
        return await _pad_out(db, pad, user)

    retry_after = await ratelimit_service.check_pin_attempt(str(pad.id), request)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many incorrect attempts. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    if not pin_service.verify_pin(pad, body.pin):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect PIN."
        )

    token, _expires = await pin_service.create_unlock(db, pad)
    response.set_cookie(
        key=pin_service.UNLOCK_COOKIE,
        value=token,
        max_age=pin_service.settings.pin_unlock_window_seconds,
        httponly=True,
        secure=pin_service.settings.cookies_secure,
        samesite="lax",
        path=pin_service.cookie_path(slug),
    )
    return await _pad_out(db, pad, user, token)


@router.get("/{slug}/raw")
async def get_pad_raw(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Raw markdown/text export — no editor chrome, suitable for curl (PRD §4)."""
    pad = await pad_service.get_pad_by_slug(db, slug)
    if pad is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pad not found.")
    if not await access_service.can_read(db, pad, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This pad is private."
        )
    unlock_token = request.cookies.get(pin_service.UNLOCK_COOKIE)
    if not await pin_service.has_pin_access(db, pad, user, unlock_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This pad is locked. Enter its PIN to view it.",
        )
    return Response(content=pad.content, media_type="text/plain; charset=utf-8")
