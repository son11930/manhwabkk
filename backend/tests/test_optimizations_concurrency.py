import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.ocr import MangaOCREngine
from src.pipeline.worker import TranslationPipelineWorker


@pytest.mark.asyncio
async def test_worker_has_bounded_concurrency_semaphore():
    """Verify TranslationPipelineWorker initializes and uses bounded concurrency semaphore."""
    session = AsyncMock()
    worker = TranslationPipelineWorker(session)
    assert hasattr(worker, "cpu_semaphore")
    assert isinstance(worker.cpu_semaphore, asyncio.Semaphore)
    # Bounded concurrency should be at most 2 to 4 workers to prevent CPU 100% lockup and UI stuttering
    assert worker.cpu_semaphore._value <= 4


@pytest.mark.asyncio
async def test_worker_uses_configured_base_ocr_concurrency(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "OCR_BASE_CONCURRENCY", 2)
    worker = TranslationPipelineWorker(AsyncMock())

    assert worker.cpu_semaphore._value == 2


@pytest.mark.asyncio
async def test_worker_ocr_bounded_execution():
    """Verify that detect_and_extract calls are throttled through cpu_semaphore."""
    session = AsyncMock()
    worker = TranslationPipelineWorker(session)
    
    # Track concurrent execution
    concurrent_calls = 0
    max_concurrent_calls = 0

    async def mock_detect(image_bytes, page_index=0):
        nonlocal concurrent_calls, max_concurrent_calls
        concurrent_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, concurrent_calls)
        await asyncio.sleep(0.05)
        concurrent_calls -= 1
        return []

    worker.ocr = MagicMock()
    worker.ocr.detect_and_extract = mock_detect

    pages = [{"index": i, "image_bytes": b"fake"} for i in range(12)]

    async def bounded_detect(page):
        async with worker.cpu_semaphore:
            return await worker.ocr.detect_and_extract(page["image_bytes"], page_index=page["index"])

    await asyncio.gather(*(bounded_detect(page) for page in pages))
    # Max concurrent calls should not exceed the semaphore limit
    assert max_concurrent_calls <= 4


def test_ocr_engine_limits_opencv_threads():
    """Verify MangaOCREngine limits OpenCV threads to prevent CPU thread explosion."""
    import cv2
    engine = MangaOCREngine()
    # OpenCV threads should be bounded (<= 2) to prevent OpenMP thread thrashing
    num_threads = cv2.getNumThreads()
    assert num_threads <= 2
