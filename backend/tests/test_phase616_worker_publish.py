"""Phase 6.16 acceptance tests for chapter-aware worker publishing.

These tests deliberately exercise the worker through its collaborators.  They
define the safety boundary for a retranslating run: unreviewed text never
changes pixels, staged objects are never reader-visible until the run is
complete, and a failed run leaves the currently published page rows intact.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from src.pipeline.contracts import OCRSegment, TranslationBatchRequest, TranslationResult
from src.pipeline.ocr import OCRExtractionResult, OCRRunMetrics
from src.pipeline.quality import QualityAssessment


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (120, 80), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _segment(page_index: int, reading_order: int, source: str) -> OCRSegment:
    return OCRSegment(
        segment_id=f"{page_index}:{reading_order}",
        page_index=page_index,
        reading_order=reading_order,
        box=(10, 10, 100, 50),
        raw_lines=(source,),
        source_text=source,
        confidence=0.96,
    )


class _RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[TranslationBatchRequest] = []

    async def translate_batch(self, request: TranslationBatchRequest) -> Sequence[TranslationResult]:
        self.requests.append(request)
        return tuple(
            TranslationResult(
                segment_id=segment.segment_id,
                source_text=segment.source_text,
                draft_thai="คำแปลร่าง",
                final_thai="คำแปลที่ผ่าน QC",
                model="test-model",
                attempts=1,
                qc_status="APPROVED",
            )
            for segment in request.segments
        )


class _PassThroughQualityGate:
    def evaluate(self, _segment, _thai_text, _glossary):
        return QualityAssessment(passed=True, issue_codes=(), requires_semantic_review=False)


class _FailingQualityGate:
    def evaluate(self, _segment, _thai_text, _glossary):
        return QualityAssessment(
            passed=False,
            issue_codes=("TIMELINE_MISMATCH",),
            requires_semantic_review=True,
        )


@pytest.mark.asyncio
async def test_worker_translates_in_reading_order_with_rolling_context_profile_and_glossary(
    test_session,
):
    """Every batch receives the final eight earlier bubbles, never page-local context."""
    from src.domains.jobs.repository import JobRepository
    from src.pipeline.worker import TranslationPipelineWorker

    job = await JobRepository(test_session).create(
        {"source_url": "https://example.test/source", "status": "PENDING", "progress_percent": 0}
    )
    image_bytes = _jpeg_bytes()
    scraper = AsyncMock()
    scraper.fetch_chapter_data.return_value = {
        "series_slug": "spare-me-great-lord",
        "series_title": "Spare Me, Great Lord!",
        "chapter_number": "153",
        "next_chapter_url": None,
        "prev_chapter_url": None,
        "pages": [
            {"index": 1, "image_bytes": image_bytes, "raw_url": "https://example.test/1.jpg"},
            {"index": 2, "image_bytes": image_bytes, "raw_url": "https://example.test/2.jpg"},
        ],
    }
    ocr = AsyncMock()
    ocr.detect_and_extract.side_effect = [
        [_segment(1, index, f"First-page source {index}") for index in range(1, 6)],
        [_segment(2, index, f"Second-page source {index}") for index in range(1, 6)],
    ]
    translator = _RecordingTranslator()
    r2 = AsyncMock()
    r2.upload_image.return_value = "https://cdn.test/staged.jpg"
    inpainter = MagicMock()
    inpainter.inpaint_image.return_value = image_bytes
    typesetter = MagicMock()
    typesetter.typeset_image.return_value = image_bytes

    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=scraper,
        ocr=ocr,
        translator=translator,
        inpainter=inpainter,
        typesetter=typesetter,
        r2_service=r2,
        quality_gate=_PassThroughQualityGate(),
        profile={"genre": "neutral"},
        glossary=({"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},),
    )

    await worker.process_job(job.id)

    assert len(translator.requests) == 2
    first, second = translator.requests
    assert first.profile == {"genre": "neutral"}
    assert first.glossary[0]["thai"] == "เครือข่ายสวรรค์"
    assert first.context == ()
    assert tuple(item["segment_id"] for item in second.context) == (
        "1:1", "1:2", "1:3", "1:4", "1:5"
    )
    assert tuple(item["final_thai"] for item in second.context) == ("คำแปลที่ผ่าน QC",) * 5


@pytest.mark.asyncio
async def test_worker_preserves_source_pixels_and_marks_warning_when_contextual_retry_fails(test_session):
    """A failed QA bubble must not be inpainted or typeset as an unsafe Thai translation."""
    from src.domains.jobs.repository import JobRepository
    from src.pipeline.worker import TranslationPipelineWorker

    job = await JobRepository(test_session).create(
        {"source_url": "https://example.test/source", "status": "PENDING", "progress_percent": 0}
    )
    image_bytes = _jpeg_bytes()
    scraper = AsyncMock()
    scraper.fetch_chapter_data.return_value = {
        "series_slug": "warning-series",
        "series_title": "Warning Series",
        "chapter_number": "1",
        "next_chapter_url": None,
        "prev_chapter_url": None,
        "pages": [{"index": 1, "image_bytes": image_bytes, "raw_url": "https://example.test/1.jpg"}],
    }
    ocr = AsyncMock()
    ocr.detect_and_extract.return_value = [_segment(1, 1, "Before, they were students, but now they are ordinary people.")]
    translator = _RecordingTranslator()
    r2 = AsyncMock()
    r2.upload_image.return_value = "https://cdn.test/staged.jpg"
    inpainter = MagicMock()
    typesetter = MagicMock()

    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=scraper,
        ocr=ocr,
        translator=translator,
        inpainter=inpainter,
        typesetter=typesetter,
        r2_service=r2,
        quality_gate=_FailingQualityGate(),
        profile={"genre": "neutral"},
        glossary=(),
    )

    completed = await worker.process_job(job.id)

    assert completed.status == "COMPLETED_WITH_WARNINGS"
    inpainter.inpaint_image.assert_not_called()
    typesetter.typeset_image.assert_not_called()
    r2.upload_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_withholds_page_when_ocr_cannot_verify_any_dialogue(test_session):
    """An empty OCR result is uncertainty, not evidence that a page is text-free."""
    from src.domains.jobs.repository import JobRepository
    from src.pipeline.worker import TranslationPipelineWorker

    job = await JobRepository(test_session).create(
        {"source_url": "https://example.test/source", "status": "PENDING", "progress_percent": 0}
    )
    image_bytes = _jpeg_bytes()
    scraper = AsyncMock()
    scraper.fetch_chapter_data.return_value = {
        "series_slug": "ocr-coverage-series",
        "series_title": "OCR Coverage Series",
        "chapter_number": "1",
        "next_chapter_url": None,
        "prev_chapter_url": None,
        "pages": [{"index": 1, "image_bytes": image_bytes, "raw_url": "https://example.test/1.jpg"}],
    }
    ocr = AsyncMock()
    ocr.detect_and_extract.return_value = []
    r2 = AsyncMock()
    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=scraper,
        ocr=ocr,
        translator=_RecordingTranslator(),
        inpainter=MagicMock(),
        typesetter=MagicMock(),
        r2_service=r2,
        quality_gate=_PassThroughQualityGate(),
        profile={"genre": "neutral"},
        glossary=(),
    )

    completed = await worker.process_job(job.id)

    assert completed.status == "COMPLETED_WITH_WARNINGS"
    r2.upload_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_withholds_page_when_ocr_reports_partial_coverage(test_session):
    """A detected bubble cannot justify publishing when coverage finds another unresolved region."""
    from src.domains.jobs.repository import JobRepository
    from src.pipeline.worker import TranslationPipelineWorker

    job = await JobRepository(test_session).create(
        {"source_url": "https://example.test/source", "status": "PENDING", "progress_percent": 0}
    )
    image_bytes = _jpeg_bytes()
    scraper = AsyncMock()
    scraper.fetch_chapter_data.return_value = {
        "series_slug": "partial-ocr-series",
        "series_title": "Partial OCR Series",
        "chapter_number": "1",
        "next_chapter_url": None,
        "prev_chapter_url": None,
        "pages": [{"index": 1, "image_bytes": image_bytes, "raw_url": "https://example.test/1.jpg"}],
    }
    ocr = AsyncMock()
    ocr.detect_and_extract.return_value = OCRExtractionResult(
        [_segment(1, 1, "Detected bubble")],
        OCRRunMetrics(
            recovery_trigger="uncovered_component",
            recovery_skipped_reason="recovery_concurrency_saturated",
            coverage_verified=False,
            uncovered_components=1,
        ),
    )
    r2 = AsyncMock()
    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=scraper,
        ocr=ocr,
        translator=_RecordingTranslator(),
        inpainter=MagicMock(),
        typesetter=MagicMock(),
        r2_service=r2,
        quality_gate=_PassThroughQualityGate(),
        profile={"genre": "neutral"},
        glossary=(),
    )

    completed = await worker.process_job(job.id)

    assert completed.status == "COMPLETED_WITH_WARNINGS"
    r2.upload_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_stages_run_objects_before_atomic_page_url_replacement(test_session):
    """Reader URLs change only once every new page exists under the same immutable run id."""
    from src.domains.jobs.repository import JobRepository
    from src.domains.manga.repository import ChapterRepository, PageRepository, SeriesRepository
    from src.pipeline.worker import TranslationPipelineWorker

    series = await SeriesRepository(test_session).create(
        {"slug": "rerun-series", "title_th": "Rerun", "source_url": "https://example.test/source"}
    )
    chapter = await ChapterRepository(test_session).create(
        {
            "series_id": series.id,
            "chapter_number": "1",
            "title_th": "Chapter 1",
            "source_url": "https://example.test/source",
            "is_translated": True,
        }
    )
    old_page = await PageRepository(test_session).create(
        {"chapter_id": chapter.id, "page_index": 1, "image_url": "https://cdn.test/old/1.jpg"}
    )
    job = await JobRepository(test_session).create(
        {"source_url": "https://example.test/source", "status": "PENDING", "progress_percent": 0}
    )
    image_bytes = _jpeg_bytes()
    scraper = AsyncMock()
    scraper.fetch_chapter_data.return_value = {
        "series_slug": "rerun-series",
        "series_title": "Rerun",
        "chapter_number": "1",
        "next_chapter_url": None,
        "prev_chapter_url": None,
        "pages": [
            {"index": 1, "image_bytes": image_bytes, "raw_url": "https://example.test/1.jpg"},
            {"index": 2, "image_bytes": image_bytes, "raw_url": "https://example.test/2.jpg"},
        ],
    }
    ocr = AsyncMock()
    ocr.detect_and_extract.side_effect = [[_segment(1, 1, "One")], [_segment(2, 1, "Two")]]
    r2 = AsyncMock()
    r2.upload_image.side_effect = [
        "https://cdn.test/runs/run-abc/1.jpg",
        "https://cdn.test/runs/run-abc/2.jpg",
    ]
    inpainter = MagicMock()
    inpainter.inpaint_image.return_value = image_bytes
    typesetter = MagicMock()
    typesetter.typeset_image.return_value = image_bytes

    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=scraper,
        ocr=ocr,
        translator=_RecordingTranslator(),
        inpainter=inpainter,
        typesetter=typesetter,
        r2_service=r2,
        quality_gate=_PassThroughQualityGate(),
        profile={"genre": "neutral"},
        glossary=(),
        run_id_factory=lambda: "run-abc",
    )

    await worker.process_job(job.id)

    assert {call.kwargs["run_id"] for call in r2.upload_image.await_args_list} == {"run-abc"}
    pages = await PageRepository(test_session).find_by_chapter(chapter.id)
    assert [page.page_index for page in pages] == [1, 2]
    assert [page.image_url for page in pages] == [
        "https://cdn.test/runs/run-abc/1.jpg",
        "https://cdn.test/runs/run-abc/2.jpg",
    ]
    assert all(page.id != old_page.id for page in pages)


@pytest.mark.asyncio
async def test_worker_upload_failure_keeps_existing_reader_pages_untouched(test_session):
    """A mid-run upload failure rolls back the publish swap; old URLs remain the reader source."""
    from src.domains.jobs.repository import JobRepository
    from src.domains.manga.repository import ChapterRepository, PageRepository, SeriesRepository
    from src.pipeline.worker import TranslationPipelineWorker

    series = await SeriesRepository(test_session).create(
        {"slug": "atomic-series", "title_th": "Atomic", "source_url": "https://example.test/source"}
    )
    chapter = await ChapterRepository(test_session).create(
        {
            "series_id": series.id,
            "chapter_number": "1",
            "title_th": "Chapter 1",
            "source_url": "https://example.test/source",
            "is_translated": True,
        }
    )
    await PageRepository(test_session).create(
        {"chapter_id": chapter.id, "page_index": 1, "image_url": "https://cdn.test/published/1.jpg"}
    )
    job = await JobRepository(test_session).create(
        {"source_url": "https://example.test/source", "status": "PENDING", "progress_percent": 0}
    )
    image_bytes = _jpeg_bytes()
    scraper = AsyncMock()
    scraper.fetch_chapter_data.return_value = {
        "series_slug": "atomic-series",
        "series_title": "Atomic",
        "chapter_number": "1",
        "next_chapter_url": None,
        "prev_chapter_url": None,
        "pages": [
            {"index": 1, "image_bytes": image_bytes, "raw_url": "https://example.test/1.jpg"},
            {"index": 2, "image_bytes": image_bytes, "raw_url": "https://example.test/2.jpg"},
        ],
    }
    ocr = AsyncMock()
    ocr.detect_and_extract.side_effect = [[_segment(1, 1, "One")], [_segment(2, 1, "Two")]]
    r2 = AsyncMock()
    r2.upload_image.side_effect = ["https://cdn.test/runs/run-fail/1.jpg", RuntimeError("R2 unavailable")]
    inpainter = MagicMock()
    inpainter.inpaint_image.return_value = image_bytes
    typesetter = MagicMock()
    typesetter.typeset_image.return_value = image_bytes

    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=scraper,
        ocr=ocr,
        translator=_RecordingTranslator(),
        inpainter=inpainter,
        typesetter=typesetter,
        r2_service=r2,
        quality_gate=_PassThroughQualityGate(),
        profile={"genre": "neutral"},
        glossary=(),
        run_id_factory=lambda: "run-fail",
    )

    with pytest.raises(RuntimeError, match="R2 unavailable"):
        await worker.process_job(job.id)

    pages = await PageRepository(test_session).find_by_chapter(chapter.id)
    assert [(page.page_index, page.image_url) for page in pages] == [
        (1, "https://cdn.test/published/1.jpg")
    ]
