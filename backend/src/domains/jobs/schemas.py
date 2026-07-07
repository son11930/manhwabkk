from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class JobSubmitReq(BaseModel):
    source_url: str

class JobStatusRes(BaseModel):
    id: str
    source_url: str
    manga_slug: Optional[str] = None
    chapter_number: Optional[str] = None
    status: str
    progress_percent: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
