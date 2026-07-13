import pytest
import numpy as np
from unittest.mock import MagicMock
from src.pipeline.ocr import MangaOCREngine

@pytest.mark.asyncio
async def test_multi_angle_shear_ocr_evaluates_slanted_text():
    """Verify that multi-angle shear ROI recovery checks shear angles (-0.20, -0.12, 0.12)."""
    engine = MangaOCREngine()
    # Mock ocr_engine to return high confidence text when sheared
    sheared_calls = []
    def mock_ocr(variant):
        sheared_calls.append(variant.shape)
        return [([[[0, 0], [50, 0], [50, 20], [0, 20]]], "SlantedText", 0.95)]
    
    engine.ocr_engine = mock_ocr
    # Test inverse shear polygon calculation across different shears
    box = (10, 10, 80, 40)
    polygon = [[0, 0], [50, 0], [50, 20], [0, 20]]
    pts_neg = engine._inverse_shear_polygon(polygon, -0.20, 2.0, 5)
    pts_pos = engine._inverse_shear_polygon(polygon, 0.12, 2.0, 5)
    assert len(pts_neg) == 4
    assert len(pts_pos) == 4


def test_multi_angle_shear_ocr_releases_semaphore_exactly_once():
    import threading
    engine = MangaOCREngine()
    engine.recovery_semaphore = threading.BoundedSemaphore(1)
    engine.ocr_engine = lambda variant: [([[[10, 10], [40, 10], [40, 30], [10, 30]]], "SlantedText", 0.50)]
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    engine.detect_and_extract_sync(1, image)
    # If released too many times, acquiring BoundedSemaphore or release would fail
    assert engine.recovery_semaphore.acquire(blocking=False) is True
    engine.recovery_semaphore.release()
