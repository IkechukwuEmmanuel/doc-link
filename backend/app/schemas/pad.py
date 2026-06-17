import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.pad import Visibility


class PadCreate(BaseModel):
    # Optional custom slug; if omitted, the server auto-generates one.
    slug: str | None = Field(default=None, max_length=40)
    content: str = ""


class PadUpdate(BaseModel):
    content: str


class PadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    owner_id: uuid.UUID | None
    visibility: Visibility
    content: str
    is_anonymous: bool
    last_opened_at: datetime
    created_at: datetime
    updated_at: datetime
