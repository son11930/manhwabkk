from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class TranslationProvider(str, Enum):
    GROQ = "groq"
    DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
    DEEPSEEK_V4_PRO = "deepseek-v4-pro"
    DEEPSEEK_CHAT = "deepseek-chat"

class JobSubmitReq(BaseModel):
    source_url: str
    translation_provider: TranslationProvider = Field(default=TranslationProvider.GROQ)

class JobStatusRes(BaseModel):
    id: str
    source_url: str
    manga_slug: Optional[str] = None
    chapter_number: Optional[str] = None
    status: str
    progress_percent: int
    error_message: Optional[str] = None
    translation_provider: str = "groq"
    requested_model: Optional[str] = None
    actual_model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate_usd: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
