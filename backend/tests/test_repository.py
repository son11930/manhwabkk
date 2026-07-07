import pytest
from src.domains.manga.repository import SeriesRepository, ChapterRepository, PageRepository
from src.domains.jobs.repository import JobRepository
from src.domains.manga.service import MangaService
from src.domains.manga.schemas import SeriesCreateReq

@pytest.mark.asyncio
async def test_manga_repository_and_cascade(test_session):
    """Test Series, Chapter, Page creation, eager loading, and cascade deletion."""
    series_repo = SeriesRepository(test_session)
    chapter_repo = ChapterRepository(test_session)
    page_repo = PageRepository(test_session)

    # 1. Create Series
    series = await series_repo.create({
        "slug": "solo-leveling",
        "title_th": "โซโลเลเวลลิง",
        "description": "มันฮวาแนวแอคชั่น"
    })
    assert series.id is not None
    assert series.slug == "solo-leveling"

    # 2. Create Chapter
    chapter = await chapter_repo.create({
        "series_id": series.id,
        "chapter_number": "1",
        "title_th": "ตอนที่ 1: จุดเริ่มต้น",
        "source_url": "http://example.com/ch1",
        "is_translated": True
    })
    assert chapter.series_id == series.id

    # 3. Create Pages
    await page_repo.create({"chapter_id": chapter.id, "page_index": 1, "image_url": "http://r2/p1.jpg"})
    await page_repo.create({"chapter_id": chapter.id, "page_index": 2, "image_url": "http://r2/p2.jpg"})

    # 4. Test find_by_slug with include_chapters
    loaded_series = await series_repo.find_by_slug("solo-leveling", include_chapters=True)
    assert loaded_series is not None
    assert len(loaded_series.chapters) == 1
    assert loaded_series.chapters[0].chapter_number == "1"

    # 5. Test Chapter reader view with pages
    loaded_ch = await chapter_repo.find_by_series_and_number(series.id, "1", include_pages=True)
    assert loaded_ch is not None
    assert len(loaded_ch.pages) == 2
    assert loaded_ch.pages[0].page_index == 1

    # 6. Test delete cascade
    await series_repo.delete(series.id)
    assert await series_repo.find_by_id(series.id) is None
    assert await chapter_repo.find_by_id(chapter.id) is None
    pages_remaining = await page_repo.find_by_chapter(chapter.id)
    assert len(pages_remaining) == 0

@pytest.mark.asyncio
async def test_job_repository_progress(test_session):
    """Test TranslationJob repository status and progress tracking."""
    job_repo = JobRepository(test_session)
    job = await job_repo.create({
        "source_url": "http://example.com/manga/ch10",
        "status": "PENDING",
        "progress_percent": 0
    })
    assert job.status == "PENDING"

    # Update progress
    updated = await job_repo.update(job.id, {
        "status": "TRANSLATING",
        "progress_percent": 50
    })
    assert updated.status == "TRANSLATING"
    assert updated.progress_percent == 50
