from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.common.repository import BaseSQLAlchemyRepository
from src.domains.manga.models import Series, Chapter, Page

class SeriesRepository(BaseSQLAlchemyRepository[Series]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Series)

    async def find_by_slug(self, slug: str, include_chapters: bool = False) -> Optional[Series]:
        query = select(Series).where(Series.slug == slug)
        if include_chapters:
            query = query.options(selectinload(Series.chapters)).execution_options(populate_existing=True)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

class ChapterRepository(BaseSQLAlchemyRepository[Chapter]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Chapter)

    async def find_by_series_and_number(self, series_id: str, chapter_number: str, include_pages: bool = False) -> Optional[Chapter]:
        query = select(Chapter).where(
            Chapter.series_id == series_id,
            Chapter.chapter_number == chapter_number
        )
        if include_pages:
            query = query.options(selectinload(Chapter.pages)).execution_options(populate_existing=True)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

class PageRepository(BaseSQLAlchemyRepository[Page]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Page)

    async def find_by_chapter(self, chapter_id: str) -> List[Page]:
        query = select(Page).where(Page.chapter_id == chapter_id).order_by(Page.page_index).execution_options(populate_existing=True)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def replace_for_chapter(
        self,
        chapter: Chapter,
        pages: List[dict],
        *,
        is_translated: bool,
    ) -> List[Page]:
        """Atomically swap reader pages only after a fully staged run succeeds."""
        try:
            existing = await self.find_by_chapter(chapter.id)
            for page in existing:
                await self.session.delete(page)
            replacements = [Page(chapter_id=chapter.id, **page) for page in pages]
            self.session.add_all(replacements)
            chapter.is_translated = is_translated
            await self.session.commit()
            for page in replacements:
                await self.session.refresh(page)
            return replacements
        except Exception:
            await self.session.rollback()
            raise
