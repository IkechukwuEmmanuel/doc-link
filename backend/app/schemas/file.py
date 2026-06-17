import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.file import ScanStatus


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pad_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    scan_status: ScanStatus
    created_at: datetime
