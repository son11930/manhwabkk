from typing import List
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db_session, async_session_maker
from src.domains.manga.service import MangaService
from src.domains.manga.schemas import SeriesRes, ChapterRes, SeriesCreateReq
from src.domains.auth.dependencies import require_super_admin
from src.domains.auth.models import User
from src.common.envelope import APIResponse, success_response
import logging

router = APIRouter(prefix="/series", tags=["Manga"])

async def auto_preload_next_chapter(next_url: str):
    """Background task to pre-fetch and translate the next chapter while user reads current chapter."""
    if not next_url or not next_url.startswith("http"):
        return
    from sqlalchemy import select
    from src.domains.jobs.models import TranslationJob
    from src.domains.manga.models import Chapter
    from src.domains.jobs.service import JobService
    from src.domains.jobs.schemas import JobSubmitReq
    from src.domains.jobs.router import run_worker_in_background

    async with async_session_maker() as session:
        try:
            # Check if next chapter already translated or job exists
            res_job = await session.execute(select(TranslationJob).where(TranslationJob.source_url == next_url))
            if res_job.scalars().first():
                return
            res_chap = await session.execute(select(Chapter).where(Chapter.source_url == next_url))
            if res_chap.scalars().first():
                return
            
            logging.info(f"[Auto-Preload] Pre-fetching next chapter from url: {next_url}")
            service = JobService(session)
            job = await service.submit_job(JobSubmitReq(source_url=next_url))
            await run_worker_in_background(job.id)
        except Exception as e:
            logging.error(f"[Auto-Preload Error] Could not preload {next_url}: {e}")

@router.get("", response_model=APIResponse[List[SeriesRes]])
async def list_series(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session)
):
    service = MangaService(session)
    series_list = await service.series_repo.find_all(skip=skip, limit=limit)
    return success_response([SeriesRes.model_validate(s) for s in series_list])

@router.post("", response_model=APIResponse[SeriesRes], dependencies=[Depends(require_super_admin)])
async def create_series(req: SeriesCreateReq, session: AsyncSession = Depends(get_db_session)):
    service = MangaService(session)
    series = await service.create_series(req)
    return success_response(SeriesRes.model_validate(series))

@router.get("/{slug}", response_model=APIResponse[SeriesRes])
async def get_series(slug: str, session: AsyncSession = Depends(get_db_session)):
    service = MangaService(session)
    series = await service.get_series_by_slug(slug)
    return success_response(SeriesRes.model_validate(series))

@router.get("/{slug}/chapters/{chapter_number}", response_model=APIResponse[ChapterRes])
async def read_chapter(
    slug: str,
    chapter_number: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session)
):
    """Reader View endpoint: fetches chapter pages from R2/local cache and triggers auto pre-loading of next chapter."""
    service = MangaService(session)
    chapter = await service.get_chapter_reader(slug, chapter_number)
    if chapter.next_chapter_url:
        background_tasks.add_task(auto_preload_next_chapter, chapter.next_chapter_url)
    return success_response(ChapterRes.model_validate(chapter))

@router.delete("/{slug}/chapters/{chapter_number}", response_model=APIResponse[bool])
async def delete_chapter(
    slug: str,
    chapter_number: str,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(require_super_admin)
):
    """Protected Super Admin action: Deletes chapter from DB and R2 storage."""
    service = MangaService(session)
    res = await service.delete_chapter_protected(slug, chapter_number)
    return success_response(res)

@router.delete("/{slug}", response_model=APIResponse[bool])
async def delete_series(
    slug: str,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(require_super_admin)
):
    """Protected Super Admin action: Deletes entire manga series from DB and R2 storage."""
    service = MangaService(session)
    res = await service.delete_series_protected(slug)
    return success_response(res)
