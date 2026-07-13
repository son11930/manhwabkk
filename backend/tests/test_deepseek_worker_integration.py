import json
from io import BytesIO

import pytest
from PIL import Image
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.worker import TranslationPipelineWorker
from src.pipeline.contracts import TranslationResult
from src.domains.jobs.models import TranslationJob
from src.infrastructure.ai.groq_client import CompletionResult
from src.infrastructure.ai.deepseek_client import DeepSeekClient
from src.config import settings
import src.pipeline.worker as worker_module


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (200, 200), "white")
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_worker_passes_completed_batch_context_to_the_next_batch(monkeypatch):
    monkeypatch.setattr(settings, "DEEPSEEK_BATCH_PAGES", 1)
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
            {"index": 1, "image_bytes": _jpeg_bytes(), "raw_url": "url1"},
            {"index": 2, "image_bytes": _jpeg_bytes(), "raw_url": "url2"},
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

    recorded_contexts = []

    async def translate_with_context(*, messages, **_kwargs):
        body = json.loads(messages[1]["content"])
        recorded_contexts.append(body["context"])
        segment_id = body["segments"][0]["segment_id"]
        return CompletionResult(
            text=json.dumps({"translations": [{"segment_id": segment_id, "text": f"ไทย {segment_id}"}]}),
            model="deepseek-chat", attempts=1, prompt_tokens=150, completion_tokens=50, total_tokens=200,
        )

    mock_client = AsyncMock()
    mock_client.model = "deepseek-chat"
    mock_client.generate_chat_completion_result.side_effect = translate_with_context

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
    assert completed.status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
    assert completed.input_tokens == 300
    assert completed.output_tokens == 100
    assert completed.cost_estimate_usd > 0.0
    assert completed.actual_model == "deepseek-chat"
    assert recorded_contexts[0] == []
    assert recorded_contexts[1] == [{"segment_id": "1:1", "source_text": "Source 1", "final_thai": "ไทย 1:1"}]


@pytest.mark.asyncio
async def test_worker_recovers_short_english_leakage_before_typesetting(monkeypatch):
    job = TranslationJob(
        id="job-deepseek-english-leakage",
        source_url="https://example.com/manga/ch1",
        translation_provider="deepseek-v4-flash",
    )

    async def mock_update(_job_id, updates):
        for key, value in updates.items():
            setattr(job, key, value)
        return job

    job_repo = MagicMock()
    job_repo.find_by_id = AsyncMock(return_value=job)
    job_repo.update = AsyncMock(side_effect=mock_update)

    scraper = MagicMock()
    scraper.fetch_chapter_data = AsyncMock(return_value={
        "series_slug": "test-manga",
        "series_title": "Test Manga",
        "chapter_number": "1",
        "pages": [{"index": 1, "image_bytes": _jpeg_bytes(), "raw_url": "url1"}],
    })
    ocr = MagicMock()
    ocr.detect_and_extract = AsyncMock(return_value=[
        {"box": [10, 10, 100, 100], "lines": ["THEM!"], "text": "THEM!"}
    ])
    groq_translator = MagicMock()
    groq_translator.translate_batch = AsyncMock(
        side_effect=AssertionError("DeepSeek recovery must not switch providers")
    )
    typesetter = MagicMock()
    def typeset_after_stage_two(*_args, **_kwargs):
        # Recovery is part of Stage 2.  Rendering must never trigger an
        # additional DeepSeek request after this point.
        assert deepseek_client.generate_chat_completion_result.call_count == 2
        return b"typeset"

    typesetter.typeset_image = MagicMock(side_effect=typeset_after_stage_two)
    inpainter = MagicMock()
    inpainter.inpaint_image = MagicMock(return_value=b"inpainted")
    storage = MagicMock()
    storage.upload_image = AsyncMock(return_value="https://cdn.example.com/page.jpg")
    page_repo = MagicMock()
    page_repo.replace_chapter_pages = AsyncMock()
    page_repo.replace_for_chapter = AsyncMock()
    profile_repo = MagicMock()
    profile_repo.latest = AsyncMock(return_value=None)
    profile_repo.append = AsyncMock()
    profile_repo.find_profile = AsyncMock(return_value={"genre": "modern_cultivation"})
    profile_repo.list_glossary = AsyncMock(return_value=[])

    stage_three_started = False
    original_info = worker_module.logger.info

    def record_stage(message, *args, **kwargs):
        nonlocal stage_three_started
        if "STAGE 3/4" in str(message):
            stage_three_started = True
        return original_info(message, *args, **kwargs)

    monkeypatch.setattr(worker_module.logger, "info", record_stage)

    deepseek_client = MagicMock(spec=DeepSeekClient)
    deepseek_client.model = "deepseek-chat"
    async def deepseek_response(*_args, **_kwargs):
        # A pre-refactor worker performed the second request in Stage 3.
        # This makes the pipeline boundary observable instead of only
        # asserting the final call count.
        assert not stage_three_started
        return deepseek_responses.pop(0)

    deepseek_responses = [
        CompletionResult(
            text='{"translations": [{"segment_id": "1:1", "text": "THEM!"}]}',
            model="deepseek-chat",
            attempts=1,
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
        ),
        CompletionResult(
            text='{"translations": [{"segment_id": "1:1", "text": "พวกเขาน่ะ!"}]}',
            model="deepseek-chat",
            attempts=1,
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
        ),
    ]
    deepseek_client.generate_chat_completion_result.side_effect = deepseek_response

    worker = TranslationPipelineWorker(
        session=MagicMock(),
        scraper=scraper,
        ocr=ocr,
        inpainter=inpainter,
        translator=groq_translator,
        typesetter=typesetter,
    )
    worker.job_repo = job_repo
    worker.series_repo = MagicMock(find_by_slug=AsyncMock(return_value=MagicMock(id="s1")))
    worker.chapter_repo = MagicMock(find_by_series_and_number=AsyncMock(return_value=MagicMock(id="c1")))
    worker.page_repo = page_repo
    worker.artifact_repo = MagicMock(append_many=AsyncMock())
    worker.profile_repo = profile_repo
    worker.r2_service = storage

    completed = await worker.process_job(job.id, ai_client=deepseek_client)

    assert completed.status == "COMPLETED"
    groq_translator.translate_batch.assert_not_awaited()
    assert deepseek_client.generate_chat_completion_result.await_count == 2
    assert typesetter.typeset_image.call_args.args[1] == [
        {"region_id": "1:bubble:1", "box": (10, 10, 100, 100), "text": "พวกเขาน่ะ!"}
    ]
