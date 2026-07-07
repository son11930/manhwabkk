from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class PageRes(BaseModel):
    id: str
    page_index: int
    image_url: str
    raw_image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ChapterRes(BaseModel):
    id: str
    series_id: str
    chapter_number: str
    title_th: Optional[str] = None
    source_url: str
    next_chapter_url: Optional[str] = None
    prev_chapter_url: Optional[str] = None
    is_translated: bool
    created_at: datetime
    pages: Optional[List[PageRes]] = None

    model_config = ConfigDict(from_attributes=True)

class SeriesRes(BaseModel):
    id: str
    slug: str
    title_th: str
    title_en: Optional[str] = None
    source_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    chapters: Optional[List[ChapterRes]] = None

    model_config = ConfigDict(from_attributes=True)

class SeriesCreateReq(BaseModel):
    slug: str
    title_th: str
    title_en: Optional[str] = None
    source_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    description: Optional[str] = None

class ChapterCreateReq(BaseModel):
    series_id: str
    chapter_number: str
    title_th: Optional[str] = None
    source_url: str
    next_chapter_url: Optional[str] = None
    prev_chapter_url: Optional[str] = None
    is_translated: bool = False
