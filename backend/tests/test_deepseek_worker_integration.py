import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.worker import TranslationPipelineWorker
from src.domains.jobs.models import TranslationJob
from src.infrastructure.ai.groq_client import CompletionResult


@pytest.mark.asyncio
async def test_worker_process_job_uses_deepseek_5page_batching():
    job = TranslationJob(
        id="job-deepseek-1",
        source_url="https://example.com/manga/ch1",
        translation_provider="deepseek-v4-flash",
    )
    async def mock_update(j_id, updates):
        for k, v in updates.items():
            setattr(job, k, v)
        return job

    job_repo = MagicMock()
    job_repo.find_by_id = AsyncMock(return_value=job)
    job_repo.update = AsyncMock(side_effect=mock_update)

    scraper = MagicMock()
    scraper.fetch_chapter_data = AsyncMock(return_value={
        "series_slug": "test-manga",
        "series_title": "Test Manga",
        "chapter_number": "1",
        "pages": [
            {"index": 1, "image_bytes": b"img1", "raw_url": "url1"},
            {"index": 2, "image_bytes": b"img2", "raw_url": "url2"},
        ]
    })

    series_repo = MagicMock()
    series_repo.find_by_slug = AsyncMock(return_value=MagicMock(id="s1"))
    chapter_repo = MagicMock()
    chapter_repo.find_by_series_and_number = AsyncMock(return_value=MagicMock(id="c1"))
    page_repo = MagicMock()
    page_repo.replace_chapter_pages = AsyncMock()
    page_repo.replace_for_chapter = AsyncMock()
    artifact_repo = MagicMock()
    artifact_repo.append_many = AsyncMock()
    profile_repo = MagicMock()
    profile_repo.latest = AsyncMock(return_value=None)
    profile_repo.append = AsyncMock()
    profile_repo.find_profile = AsyncMock(return_value={"genre": "modern_cultivation"})
    profile_repo.list_glossary = AsyncMock(return_value=[])

    ocr = MagicMock()
    ocr.detect_and_extract = AsyncMock(side_effect=lambda img, page_index: [
        {"id": f"{page_index}:1", "box": [10, 10, 100, 100], "lines": ["Text"], "text": f"Source {page_index}"}
    ])

    typesetter = MagicMock()
    typesetter.render_translated_page = AsyncMock(return_value=b"rendered")
    typesetter.typeset_image = MagicMock(return_value=b"typeset")
    inpainter = MagicMock()
    inpainter.inpaint_image = MagicMock(return_value=b"inpainted")
    storage = MagicMock()
    storage.upload_bytes = AsyncMock(return_value="https://cdn.example.com/page.jpg")
    storage.upload_image = AsyncMock(return_value="https://cdn.example.com/page.jpg")

    mock_client = AsyncMock()
    mock_client.model = "deepseek-chat"
    mock_client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": [{"segment_id": "1:1", "text": "แปล 1"}, {"segment_id": "2:1", "text": "แปล 2"}]}',
        model="deepseek-chat",
        attempts=1,
        prompt_tokens=300,
        completion_tokens=100,
        total_tokens=400,
    )

    worker = TranslationPipelineWorker(
        session=MagicMock(),
        scraper=scraper,
        ocr=ocr,
        inpainter=inpainter,
        typesetter=typesetter,
    )
    worker.job_repo = job_repo
    worker.series_repo = series_repo
    worker.chapter_repo = chapter_repo
    worker.page_repo = page_repo
    worker.artifact_repo = artifact_repo
    worker.profile_repo = profile_repo
    worker.r2_service = storage

    completed = await worker.process_job("job-deepseek-1", ai_client=mock_client)
    assert completed.status == "COMPLETED"
    assert completed.input_tokens == 300
    assert completed.output_tokens == 100
    assert completed.cost_estimate_usd > 0.0
    assert completed.actual_model == "deepseek-chat"
