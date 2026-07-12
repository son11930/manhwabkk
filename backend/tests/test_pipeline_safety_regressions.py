from PIL import Image
import numpy as np

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
