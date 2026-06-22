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
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
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
        UniqueConstraint("pad_id", "user_id", name="uqe_pad_collaborator_pad_user"),
    )
