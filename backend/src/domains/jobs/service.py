from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.domains.jobs.repository import JobRepository
from src.domains.jobs.models import TranslationJob
from src.domains.jobs.schemas import JobSubmitReq
from src.common.exceptions import NotFoundError

class JobService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = JobRepository(session)

    async def submit_job(self, req: JobSubmitReq) -> TranslationJob:
        provider_val = req.translation_provider.value if hasattr(req.translation_provider, "value") else str(req.translation_provider)
        return await self.repo.create({
            "source_url": req.source_url,
            "translation_provider": provider_val,
            "status": "PENDING",
            "progress_percent": 0
        })

    async def get_job_status(self, job_id: str) -> TranslationJob:
        job = await self.repo.find_by_id(job_id)
        if not job:
            raise NotFoundError("TranslationJob", job_id)
        return job

    async def update_progress(self, job_id: str, status: str, progress: int, error: Optional[str] = None) -> Optional[TranslationJob]:
        return await self.repo.update(job_id, {
            "status": status,
            "progress_percent": progress,
            "error_message": error
        })

    async def cancel_job(self, job_id: str) -> TranslationJob:
        job = await self.repo.find_by_id(job_id)
        if not job:
            raise NotFoundError("TranslationJob", job_id)
        updated = await self.repo.update(job_id, {
            "status": "CANCELLED",
            "error_message": "ผู้ใช้งานยกเลิกการทำงานของระบบแปลภาษา (User cancelled translation job)"
        })
        return updated or job
