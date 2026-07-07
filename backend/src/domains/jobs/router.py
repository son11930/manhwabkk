from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db_session
from src.domains.jobs.service import JobService
from src.domains.jobs.schemas import JobSubmitReq, JobStatusRes
from src.common.envelope import APIResponse, success_response

router = APIRouter(prefix="/jobs", tags=["Jobs"])

@router.post("/submit", response_model=APIResponse[JobStatusRes])
async def submit_translation_job(req: JobSubmitReq, session: AsyncSession = Depends(get_db_session)):
    service = JobService(session)
    job = await service.submit_job(req)
    # Background worker dispatcher will be hooked here in Phase 2
    return success_response(JobStatusRes.model_validate(job))

@router.get("/{job_id}", response_model=APIResponse[JobStatusRes])
async def get_job_status(job_id: str, session: AsyncSession = Depends(get_db_session)):
    service = JobService(session)
    job = await service.get_job_status(job_id)
    return success_response(JobStatusRes.model_validate(job))
