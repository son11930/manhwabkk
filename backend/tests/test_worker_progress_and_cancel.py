import pytest
from unittest.mock import AsyncMock, patch
from src.pipeline.worker import TranslationPipelineWorker
from src.domains.jobs.models import TranslationJob

@pytest.mark.asyncio
async def test_worker_respects_cancellation(test_session):
    worker = TranslationPipelineWorker(test_session)
    # Create a cancelled job
    job = TranslationJob(
        source_url="https://example.com/cancelled",
        manga_slug="test-cancelled",
        chapter_number=1,
        status="CANCELLED",
        progress_percent=30,
        translation_provider="groq"
    )
    test_session.add(job)
    await test_session.commit()

    # Process job should return early without changing CANCELLED status
    await worker.process_job(job.id)
    await test_session.refresh(job)
    assert job.status == "CANCELLED"
