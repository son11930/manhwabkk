from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from src.domains.manga.repository import SeriesRepository, ChapterRepository, PageRepository
from src.domains.manga.models import Series, Chapter, Page
from src.domains.manga.schemas import SeriesCreateReq, ChapterCreateReq
from src.common.exceptions import NotFoundError, ValidationError
from src.infrastructure.storage.r2_service import R2StorageService

class MangaService:
    def __init__(self, session: AsyncSession, r2_service: Optional[R2StorageService] = None):
        self.session = session
        self.series_repo = SeriesRepository(session)
        self.chapter_repo = ChapterRepository(session)
        self.page_repo = PageRepository(session)
        self.r2_service = r2_service or R2StorageService()

    async def get_series_by_slug(self, slug: str) -> Series:
        series = await self.series_repo.find_by_slug(slug, include_chapters=True)
        if not series:
            raise NotFoundError("Series", slug)
        return series

    async def create_series(self, req: SeriesCreateReq) -> Series:
        existing = await self.series_repo.find_by_slug(req.slug)
        if existing:
            raise ValidationError(f"Series with slug '{req.slug}' already exists.")
        return await self.series_repo.create(req.model_dump())

    async def get_chapter_reader(self, series_slug: str, chapter_number: str) -> Chapter:
        """
        Core Concept: First person translates, next readers read free.
        Fetches chapter and pages from local database cache if translated.
        """
        series = await self.get_series_by_slug(series_slug)
        chapter = await self.chapter_repo.find_by_series_and_number(series.id, chapter_number, include_pages=True)
        if not chapter:
            raise NotFoundError("Chapter", f"{series_slug}/ch-{chapter_number}")
        return chapter

    async def delete_chapter_protected(self, series_slug: str, chapter_number: str) -> bool:
        """
        Protected Super Admin action: Deletes chapter from SQLite DB and removes images from R2 bucket.
        """
        series = await self.series_repo.find_by_slug(series_slug)
        if not series:
            raise NotFoundError("Series", series_slug)
        
        chapter = await self.chapter_repo.find_by_series_and_number(series.id, chapter_number)
        if not chapter:
            raise NotFoundError("Chapter", chapter_number)

        # 1. Delete images from Cloudflare R2
        await self.r2_service.delete_chapter_images(series_slug, chapter_number)

        # 2. Delete chapter from DB (cascade deletes pages)
        return await self.chapter_repo.delete(chapter.id)

    async def delete_series_protected(self, series_slug: str) -> bool:
        """
        Protected Super Admin action: Deletes entire manga series from SQLite DB and removes all images from R2 bucket.
        """
        series = await self.series_repo.find_by_slug(series_slug)
        if not series:
            raise NotFoundError("Series", series_slug)

        # 1. Delete all series images from Cloudflare R2
        await self.r2_service.delete_series_images(series_slug)

        # 2. Delete series from DB (cascade deletes chapters and pages)
        return await self.series_repo.delete(series.id)
