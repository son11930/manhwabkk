from datetime import datetime, timezone
import uuid
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.database import Base

class Series(Base):
    __tablename__ = "series"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    title_th: Mapped[str] = mapped_column(String(255), nullable=False)
    title_en: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    cover_image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    chapters: Mapped[List["Chapter"]] = relationship("Chapter", back_populates="series", cascade="all, delete-orphan", lazy="selectin")

class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    series_id: Mapped[str] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), index=True, nullable=False)
    chapter_number: Mapped[str] = mapped_column(String(50), nullable=False)
    title_th: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    next_chapter_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    prev_chapter_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_translated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    series: Mapped["Series"] = relationship("Series", back_populates="chapters", lazy="selectin")
    pages: Mapped[List["Page"]] = relationship("Page", back_populates="chapter", cascade="all, delete-orphan", order_by="Page.page_index", lazy="selectin")

class Page(Base):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="pages", lazy="selectin")
