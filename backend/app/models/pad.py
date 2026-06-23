import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Visibility(str, enum.Enum):
    public_edit = "public_edit"
    public_view = "public_view"
    private = "private"


class CollaboratorRole(str, enum.Enum):
    viewer = "viewer"
    editor = "editor"


class PinFormat(str, enum.Enum):
    numeric = "numeric"
    alphanumeric = "alphanumeric"


class Pad(Base, TimestampMixin):
    __tablename__ = "pads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility"),
        default=Visibility.public_edit,
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text('false')
    )

    # Phase 1: plain text body. Phase 2 adds the CRDT snapshot alongside.
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    crdt_snapshot: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    crdt_snapshot_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Phase 6: storage-cost marker for pads untouched past the cold-storage
    # window. NOT deletion and NOT user-facing "expiry" — see DECISIONS.md.
    cold_storage_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )

    # PIN protection (orthogonal to `visibility`): anyone with the link + the PIN
    # can get in. `pin_protected` is an explicit flag, not inferred from pin_hash,
    # for clarity. Never store the PIN in plaintext (argon2 hash only).
    pin_protected: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pin_format: Mapped[PinFormat | None] = mapped_column(
        Enum(PinFormat, name="pin_format"), nullable=True
    )


class PadCollaborator(Base):
    __tablename__ = "pad_collaborators"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pad_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[CollaboratorRole] = mapped_column(
        Enum(CollaboratorRole, name="collaborator_role"),
        nullable=False,
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("pad_id", "user_id", name="uq_pad_collaborator_pad_user"),
    )


class PadPinUnlock(Base):
    """A time-boxed unlock session for a PIN-protected pad.

    The opaque ``unlock_token`` is handed to the client as an httpOnly cookie;
    access is granted while ``expires_at`` is in the future. Expiry is checked on
    every access, so stale rows are harmless — a cleanup job just reaps them.
    """

    __tablename__ = "pad_pin_unlocks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pad_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unlock_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
