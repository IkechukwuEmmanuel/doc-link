import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.pad import CollaboratorRole, PinFormat, Visibility


class PadCreate(BaseModel):
    # Optional custom slug; if omitted, the server auto-generates one.
    slug: str | None = Field(default=None, max_length=40)
    content: str = ""


class PadUpdate(BaseModel):
    """Content (body) update — separate auth path from metadata (see PadPatch)."""

    content: str


class PadPatch(BaseModel):
    """Owner-only metadata update: rename, change visibility, archive/unarchive,
    set/clear PIN protection.

    All fields optional; only the provided keys are applied (partial update).
    Setting ``pin_protected: true`` requires ``pin`` (and ``pin_format``).
    """

    name: str | None = Field(default=None, max_length=120)
    visibility: Visibility | None = None
    is_archived: bool | None = None
    pin_protected: bool | None = None
    pin: str | None = Field(default=None, max_length=64)
    pin_format: PinFormat | None = None


class PinUnlockIn(BaseModel):
    pin: str = Field(min_length=1, max_length=64)


class PadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str | None
    owner_id: uuid.UUID | None
    visibility: Visibility
    is_archived: bool
    content: str
    is_anonymous: bool
    last_opened_at: datetime
    created_at: datetime
    updated_at: datetime
    pin_protected: bool = False
    pin_format: PinFormat | None = None
    # Computed per-request for the authenticated viewer: may they edit content?
    can_edit: bool = True
    # True when the pad is PIN-gated and this requester hasn't unlocked it; when
    # set, `content` is withheld (empty) so locked content never leaks.
    locked: bool = False


class PadListItem(BaseModel):
    """Row in the dashboard pad list (no content body — kept light)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str | None
    visibility: Visibility
    is_archived: bool
    pin_protected: bool = False
    last_opened_at: datetime
    created_at: datetime
    updated_at: datetime
    file_count: int = 0
    size_bytes: int = 0


class CollaboratorIn(BaseModel):
    email: EmailStr
    role: CollaboratorRole = CollaboratorRole.editor


class CollaboratorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: CollaboratorRole
    invited_at: datetime
    accepted_at: datetime | None
