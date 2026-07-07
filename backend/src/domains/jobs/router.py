from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db_session, async_session_maker
from src.domains.jobs.service import JobService
from src.domains.jobs.schemas import JobSubmitReq, JobStatusRes
from src.common.envelope import APIResponse, success_response
import logging

router = APIRouter(prefix="/jobs", tags=["Jobs"])

async def run_worker_in_background(job_id: str):
    from src.pipeline.worker import TranslationPipelineWorker
    async with async_session_maker() as session:
        worker = TranslationPipelineWorker(session)
        try:
            logging.info(f"[Pipeline Worker] Starting job {job_id}...")
            await worker.process_job(job_id)
            logging.info(f"[Pipeline Worker] Completed job {job_id} successfully!")
        except Exception as e:
            logging.error(f"[Pipeline Worker Error] Job {job_id} failed: {e}")

@router.post("/submit", response_model=APIResponse[JobStatusRes])
async def submit_translation_job(
    req: JobSubmitReq,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session)
):
    service = JobService(session)
    job = await service.submit_job(req)
    background_tasks.add_task(run_worker_in_background, job.id)
    return success_response(JobStatusRes.model_validate(job))

@router.get("/{job_id}", response_model=APIResponse[JobStatusRes])
async def get_job_status(job_id: str, session: AsyncSession = Depends(get_db_session)):
    service = JobService(session)
    job = await service.get_job_status(job_id)
    return success_response(JobStatusRes.model_validate(job))
