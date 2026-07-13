"""Tests for Chapter 149 Translation Reliability Recovery Plan (P0-P4)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.pipeline.contracts import OCRSegment
from src.pipeline.deepseek_batch_translator import (
    DeepSeekBatchTranslator,
    parse_deepseek_batch_response,
)


def test_deepseek_batch_parser_outcome_types():
    expected_ids = ("1:1", "1:2")

    # 1. Complete
    res_complete = parse_deepseek_batch_response(
        '{"translations": [{"segment_id": "1:1", "text": "สวัสดี"}, {"segment_id": "1:2", "text": "ครับ"}]}',
        expected_ids,
    )
    assert res_complete.outcome_type == "COMPLETE"
    assert len(res_complete.translations) == 2

    # 2. Empty content
    res_empty = parse_deepseek_batch_response('{"translations": []}', expected_ids)
    assert res_empty.outcome_type == "EMPTY_CONTENT"
    assert len(res_empty.translations) == 0

    # 3. Invalid JSON (no translations array at all)
    res_invalid = parse_deepseek_batch_response("not json at all", expected_ids)
    assert res_invalid.outcome_type in ("INVALID_JSON", "EMPTY_CONTENT")
    assert len(res_invalid.translations) == 0

    # 4. Partial / Missing IDs
    res_partial = parse_deepseek_batch_response(
        '{"translations": [{"segment_id": "1:1", "text": "สวัสดี"}]}',
        expected_ids,
    )
    assert res_partial.outcome_type == "PARTIAL"
    assert res_partial.missing_ids == ("1:2",)


@pytest.mark.asyncio
async def test_deepseek_batch_translator_does_not_raise_runtime_error_on_empty_translations():
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.text = '{"translations": []}'
    mock_result.model = "deepseek-chat"
    mock_result.attempts = 1
    mock_result.prompt_tokens = 10
    mock_result.completion_tokens = 5
    mock_client.generate_chat_completion_result = AsyncMock(return_value=mock_result)

    translator = DeepSeekBatchTranslator(mock_client, provider="deepseek-chat")
    pages = [[OCRSegment("1:1", 1, 1, (0, 0, 10, 10), ("Hello",), "Hello", 0.9)]]

    # Should return BatchTranslationResult with outcome_type EMPTY_CONTENT instead of RuntimeError
    res = await translator.translate_page_batch(pages)
    assert res.parse_outcome is not None
    assert res.parse_outcome.outcome_type == "EMPTY_CONTENT"
    assert res.translations == {}


@pytest.mark.asyncio
async def test_ocr_diagnostic_metrics_do_not_block_approved_dialogue_publishing():
    from io import BytesIO
    from PIL import Image
    from src.domains.jobs.models import TranslationJob
    from src.pipeline.ocr import OCRExtractionResult, OCRRunMetrics
    from src.pipeline.worker import TranslationPipelineWorker

    def _jpeg_bytes() -> bytes:
        image = Image.new("RGB", (100, 100), "white")
        buf = BytesIO()
        image.save(buf, format="JPEG")
        return buf.getvalue()

    job = TranslationJob(
        id="job-ocr-diag-1",
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
    scraper.fetch_chapter_data = AsyncMock(
        return_value={
            "series_slug": "test-manga",
            "series_title": "Test Manga",
            "chapter_number": "1",
            "pages": [{"index": 1, "image_bytes": _jpeg_bytes(), "raw_url": "url1"}],
        }
    )

    series_repo = MagicMock()
    series_repo.find_by_slug = AsyncMock(return_value=MagicMock(id="s1"))
    chapter_repo = MagicMock()
    chapter_repo.find_by_series_and_number = AsyncMock(return_value=MagicMock(id="c1"))
    page_repo = MagicMock()
    page_repo.replace_chapter_pages = AsyncMock()
    page_repo.replace_for_chapter = AsyncMock()
    artifact_repo = MagicMock()
    artifact_repo.append_many = AsyncMock()

    class MockBatchList(list):
        pass

    batch_result = MockBatchList([OCRSegment("1:1", 1, 1, (10, 10, 50, 50), ("Hello",), "Hello", 0.96, "1:bubble:1")])
    batch_result.metrics = MagicMock()
    batch_result.metrics.safe_log_fields.return_value = {"coverage_verified": True, "recovery_trigger": "none"}
    ocr = MagicMock()
    ocr.detect_and_extract = AsyncMock(return_value=batch_result)
    ocr.last_run_metrics = {"coverage_verified": True, "queue_wait_ms": 0, "process_ms": 10}

    translator = MagicMock()
    quality = MagicMock()
    from src.pipeline.quality import QualityAssessment
    quality.evaluate.return_value = QualityAssessment(passed=True, issue_codes=(), requires_semantic_review=False)

    worker = TranslationPipelineWorker(
        session=MagicMock(),
        scraper=scraper,
        ocr=ocr,
        inpainter=MagicMock(),
        typesetter=MagicMock(),
    )
    worker.job_repo = job_repo
    worker.series_repo = series_repo
    worker.chapter_repo = chapter_repo
    worker.page_repo = page_repo
    worker.artifact_repo = artifact_repo
    worker.quality_gate = quality
    worker.profile_repo = MagicMock()
    worker.profile_repo.latest = AsyncMock(return_value=None)
    worker.profile_repo.append = AsyncMock()
    worker.glossary_repo = MagicMock()
    worker.glossary_repo.list_for_series = AsyncMock(return_value=[])
    worker.r2_service = MagicMock()
    worker.r2_service.upload_image = AsyncMock(return_value="https://cdn.example.com/ch1/1.jpg")

    # Mock Stage 2 deepseek translation
    worker._stage2_deepseek_translation = AsyncMock(return_value=({"1:1": "สวัสดี"}, (), 10, 10, 0.01, "deepseek-v4-flash", None))

    await worker.process_job("job-ocr-diag-1")
    assert job.status == "COMPLETED"
    page_repo.replace_for_chapter.assert_called_once()


@pytest.mark.asyncio
async def test_adaptive_batch_splitting_recovers_missing_segments():
    from src.pipeline.deepseek_batch_translator import BatchTranslationResult, DeepSeekBatchParseOutcome
    from src.pipeline.worker import TranslationPipelineWorker

    segments = [
        OCRSegment("1:1", 1, 1, (10, 10, 50, 50), ("One",), "One", 0.99, "1:bubble:1"),
        OCRSegment("1:2", 1, 2, (10, 60, 50, 100), ("Two",), "Two", 0.99, "1:bubble:2"),
        OCRSegment("1:3", 1, 3, (60, 10, 100, 50), ("Three",), "Three", 0.99, "1:bubble:3"),
        OCRSegment("1:4", 1, 4, (60, 60, 100, 100), ("Four",), "Four", 0.99, "1:bubble:4"),
    ]

    mock_translator = MagicMock()
    # First call (4 segments) returns only 1:1
    res1 = BatchTranslationResult(
        translations={"1:1": "หนึ่ง"},
        model="deepseek-v4-flash",
        attempts=1,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        parse_outcome=DeepSeekBatchParseOutcome({"1:1": "หนึ่ง"}, ("1:2", "1:3", "1:4"), (), ()),
    )
    # Second call (split chunk 1:2, 1:3) returns 1:2, 1:3
    res2 = BatchTranslationResult(
        translations={"1:2": "สอง", "1:3": "สาม"},
        model="deepseek-v4-flash",
        attempts=1,
        input_tokens=5,
        output_tokens=3,
        cost_usd=0.0005,
        parse_outcome=DeepSeekBatchParseOutcome({"1:2": "สอง", "1:3": "สาม"}, (), (), ()),
    )
    # Third call (split chunk 1:4) returns 1:4
    res3 = BatchTranslationResult(
        translations={"1:4": "สี่"},
        model="deepseek-v4-flash",
        attempts=1,
        input_tokens=8,
        output_tokens=5,
        cost_usd=0.0008,
        parse_outcome=DeepSeekBatchParseOutcome({"1:4": "สี่"}, (), (), ()),
    )

    mock_translator.translate_page_batch = AsyncMock(side_effect=[res1, res2, res3])

    worker = TranslationPipelineWorker(
        session=MagicMock(),
        scraper=MagicMock(),
        ocr=MagicMock(),
        inpainter=MagicMock(),
        typesetter=MagicMock(),
    )
    worker.profile = {"genre": "modern_cultivation"}
    worker.glossary = ()

    merged_res = await worker._adaptive_translate_segments(
        segments=segments,
        batch_translator=mock_translator,
        glossary=(),
        context=(),
        profile={"genre": "modern_cultivation"},
        job_id="test-job",
        budget_reserve_fn=lambda c: True,
        budget_settle_fn=lambda c, a: None,
    )

    assert merged_res.translations == {
        "1:1": "หนึ่ง",
        "1:2": "สอง",
        "1:3": "สาม",
        "1:4": "สี่",
    }
    assert mock_translator.translate_page_batch.call_count == 3


