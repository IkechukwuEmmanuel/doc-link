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
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Visibility(str, enum.Enum):
    public_edit = "public_edit"
    public_view = "public_view"
    private = "private"


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
