import logging
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.worker import TranslationPipelineWorker


@pytest.mark.asyncio
async def test_worker_process_job_logs_progress_and_error(caplog):
    """Verify that TranslationPipelineWorker logs lifecycle events and captures full exception tracebacks."""
    session = AsyncMock()
    worker = TranslationPipelineWorker(session)

    # Mock job repository
    mock_job = MagicMock()
    mock_job.source_url = "https://example.com/chapter-1"
    worker.job_repo = MagicMock()
    worker.job_repo.find_by_id = AsyncMock(return_value=mock_job)
    worker.job_repo.update = AsyncMock()

    # Simulate scraper failure to verify failure logging
    worker.scraper = MagicMock()
    worker.scraper.fetch_chapter_data = AsyncMock(side_effect=RuntimeError("Test Scraper Connection Error"))

    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError, match="Test Scraper Connection Error"):
            await worker.process_job("test-job-123")

    # Verify start log and exception log are recorded
    log_messages = [record.message for record in caplog.records]
    assert any("Starting translation job test-job-123" in msg for msg in log_messages)
    assert any("Job test-job-123 FAILED" in msg for msg in log_messages)
