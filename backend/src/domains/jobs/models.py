from datetime import datetime, timezone
import uuid
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base

class TranslationJob(Base):
    __tablename__ = "translation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    manga_slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    chapter_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")  # PENDING, SCRAPING, TRANSLATING, COMPLETED, FAILED
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
