from PIL import Image
import numpy as np
from pathlib import Path

from src.pipeline.contracts import OCRSegment
from src.pipeline.ocr import MangaOCREngine
from src.pipeline.quality import TranslationQualityGate
from src.pipeline.typesetter import TypesetterEngine


def _segment(source: str) -> OCRSegment:
    return OCRSegment("1:1", 1, 1, (10, 10, 110, 60), (source,), source, 0.9)


def test_ocr_does_not_merge_nearby_separate_bubbles():
    engine = MangaOCREngine.__new__(MangaOCREngine)
    lines = [
        {"left": 10, "top": 10, "right": 150, "bottom": 45, "text": "LEFT", "confidence": 0.9},
        {"left": 170, "top": 50, "right": 310, "bottom": 85, "text": "RIGHT", "confidence": 0.9},
    ]
    assert len(engine._group_lines(lines, page_width=400, page_height=300)) == 2


def test_typesetter_does_not_erase_image_rectangle_before_drawing():
    image = Image.new("RGB", (160, 100), (255, 255, 255))
    image.putpixel((20, 20), (220, 0, 0))
    assert TypesetterEngine().render_text_in_box(image, "test", (10, 10, 150, 90)).getpixel((20, 20)) == (220, 0, 0)


def test_quality_gate_flags_female_entity_referred_to_with_male_pronoun():
    assessment = TranslationQualityGate().evaluate(
        _segment("Lu Xiaoyu is my younger sister."),
        "นาย Lu Xiaoyu เป็นน้องสาวของฉัน",
        ({"source": "Lu Xiaoyu", "thai": "Lu Xiaoyu", "locked": True, "gender": "female"},),
    )
    assert "PRONOUN_GENDER_MISMATCH" in assessment.issue_codes


def test_ocr_detects_and_normalizes_a_slanted_text_polygon():
    angle = MangaOCREngine._polygon_angle(((0, 0), (100, 18), (100, 48), (0, 30)))
    assert angle == 10


def test_ocr_prefers_deskewed_candidate_that_preserves_words_and_punctuation():
    original_score = MangaOCREngine._candidate_score("LU SHU S VOICE", 0.81)
    deskewed_score = MangaOCREngine._candidate_score("LU SHU'S VOICE!!", 0.80)
    assert deskewed_score > original_score


def test_ocr_deskew_rejects_invalid_or_out_of_bounds_quadrilaterals():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    assert MangaOCREngine._deskew_roi(image, ((0, 0), (40, 0), (40, 0), (0, 40))) is None
    assert MangaOCREngine._deskew_roi(image, ((0, 0), (120, 0), (120, 40), (0, 40))) is None


def test_inverse_shear_restores_coordinates_after_negative_shear_offset():
    original = MangaOCREngine._inverse_shear_polygon(((76, 40),), -0.22, 2.0, 18)
    assert original == ((33.4, 20.0),)


def test_high_confidence_ellipsis_does_not_trigger_italic_recovery():
    assert MangaOCREngine._needs_italic_recovery([
        {"text": "WAIT...", "confidence": 0.94},
        {"text": "I AM HERE.", "confidence": 0.92},
    ]) is False


def test_panel_border_does_not_trigger_full_page_italic_recovery():
    image = Image.new("RGB", (300, 300), color="white")
    image_array = np.array(image)
    image_array[150:154, :] = 0
    success, encoded = __import__("cv2").imencode(".png", image_array)
    assert success

    engine = MangaOCREngine.__new__(MangaOCREngine)
    engine.is_ready = True
    calls = 0

    def fake_ocr(page):
        nonlocal calls
        calls += 1
        if page.shape[1] != 300:
            raise AssertionError("panel border must not trigger recovery variants")
        return ([(((30, 30), (230, 30), (230, 60), (30, 60)), "COMPLETE DIALOGUE", 0.95)], None)

    engine.ocr_engine = fake_ocr

    segments = engine.detect_and_extract_sync(encoded.tobytes(), page_index=1)

    assert [segment.source_text for segment in segments] == ["COMPLETE DIALOGUE"]
    assert calls == 1


def test_ocr_recovers_missing_italic_line_even_when_primary_confidence_is_high():
    image = Image.new("RGB", (300, 300), color="white")
    image_bytes = __import__("io").BytesIO()
    image.save(image_bytes, format="PNG")
    engine = MangaOCREngine.__new__(MangaOCREngine)
    engine.is_ready = True

    def fake_ocr(image_array):
        if image_array.shape[1] == 300:
            return ([(((20, 20), (260, 20), (260, 55), (20, 55)), "THIRTY-FINE", 0.80)], None)
        return ([(((60, 160), (520, 160), (520, 230), (60, 230)), "STONES!", 0.93)], None)

    engine.ocr_engine = fake_ocr

    segments = engine.detect_and_extract_sync(image_bytes.getvalue(), page_index=1)

    assert any("STONES!" in segment.source_text for segment in segments)


def test_italic_fixture_recovery_adds_text_missing_from_primary_ocr():
    engine = MangaOCREngine()
    fixture = Path(__file__).resolve().parents[2] / "img" / "1.PNG"

    segments = engine.detect_and_extract_sync(fixture.read_bytes(), page_index=1)

    assert any("VOICE" in segment.source_text.upper() for segment in segments)


def test_italic_fixture_recovery_adds_missing_bottom_line():
    engine = MangaOCREngine()
    fixture = Path(__file__).resolve().parents[2] / "img" / "2.PNG"

    segments = engine.detect_and_extract_sync(fixture.read_bytes(), page_index=2)

    assert any("STONES" in segment.source_text.upper() for segment in segments)
