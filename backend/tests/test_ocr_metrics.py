import io

from PIL import Image

from src.pipeline.ocr import MangaOCREngine, OCRExtractionResult


def _image_bytes() -> bytes:
    image = Image.new("RGB", (300, 200), color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_ocr_result_reports_base_pass_pixel_workload_without_dialogue() -> None:
    engine = MangaOCREngine.__new__(MangaOCREngine)
    engine.is_ready = True
    engine.ocr_engine = lambda image: ([
        (((20, 20), (180, 20), (180, 50), (20, 50)), "DIALOGUE MUST NOT APPEAR IN METRICS", 0.95),
    ], None)

    result = engine.detect_and_extract_sync(_image_bytes(), page_index=4)

    assert isinstance(result, OCRExtractionResult)
    assert result.metrics.base_passes == 1
    assert result.metrics.roi_passes == 0
    assert result.metrics.full_page_passes == 1
    assert result.metrics.base_pixels == 300 * 200
    assert result.metrics.roi_pixels == 0
    assert "DIALOGUE" not in result.metrics.safe_log_fields()


def test_ocr_settings_clamp_recovery_budget() -> None:
    from src.pipeline.ocr import OCRRunBudget

    budget = OCRRunBudget(max_rois=99, max_pixel_ratio=99.0)

    assert budget.max_rois == 8
    assert budget.max_pixel_ratio == 4.0


def test_ocr_recovery_does_not_block_a_base_worker_when_capacity_is_busy() -> None:
    engine = MangaOCREngine.__new__(MangaOCREngine)
    engine.is_ready = True
    engine.ocr_engine = lambda image: ([
        (((20, 20), (180, 20), (180, 50), (20, 50)), "LOW CONFIDENCE", 0.60),
    ], None)
    from src.pipeline.ocr import OCRRunBudget
    import threading

    engine.run_budget = OCRRunBudget(max_rois=1, max_pixel_ratio=2.0)
    engine.recovery_semaphore = threading.BoundedSemaphore(1)
    assert engine.recovery_semaphore.acquire(blocking=False)
    try:
        result = engine.detect_and_extract_sync(_image_bytes(), page_index=4)
    finally:
        engine.recovery_semaphore.release()

    assert result.metrics.roi_passes == 0
    assert result.metrics.recovery_skipped_reason == "recovery_concurrency_saturated"
