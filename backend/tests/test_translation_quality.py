import json
from pathlib import Path

import pytest


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chapter_153_semantic_cases.json"


def _segment(source_text: str, *, segment_id: str = "1:1"):
    from src.pipeline.contracts import OCRSegment

    return OCRSegment(
        segment_id=segment_id,
        page_index=1,
        reading_order=1,
        box=(10, 20, 200, 100),
        raw_lines=(source_text,),
        source_text=source_text,
        confidence=0.95,
    )


@pytest.mark.parametrize(
    ("source", "thai", "expected_issue"),
    [
        ("He has 12 stones.", "เขามีหิน 21 ก้อน", "NUMBER_MISMATCH"),
        ("She reached Rank D.", "เธอเลื่อนถึงระดับ E", "RANK_MISMATCH"),
        ("I will not go.", "ฉันจะไป", "NEGATION_MISMATCH"),
        (
            "Before they were students, but now they are ordinary people.",
            "พวกเขาเป็นนักเรียนธรรมดา",
            "TIMELINE_MISMATCH",
        ),
        ("Welcome back.", "Here is the translation: ยินดีต้อนรับกลับ", "META_TEXT"),
        ("Welcome back to the village.", "ยินดีต้อนรับกลับ to the village", "ENGLISH_LEAKAGE"),
        (
            "This long source sentence contains important details about the entire dangerous mission.",
            "ภารกิจ",
            "LENGTH_RATIO_OUTLIER",
        ),
    ],
)
def test_deterministic_quality_gate_detects_meaning_risk(source, thai, expected_issue):
    from src.pipeline.quality import TranslationQualityGate

    assessment = TranslationQualityGate().evaluate(_segment(source), thai, glossary=())

    assert expected_issue in assessment.issue_codes
    assert assessment.passed is False


def test_deterministic_quality_gate_enforces_locked_glossary_terms():
    from src.pipeline.quality import TranslationQualityGate

    assessment = TranslationQualityGate().evaluate(
        _segment("The Dragnet members arrived."),
        "สมาชิกแดร็กเน็ตมาถึงแล้ว",
        glossary=(
            {"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},
            {"source": "members", "thai": "สมาชิก", "locked": False},
        ),
    )

    assert "LOCKED_TERM_MISMATCH" in assessment.issue_codes
    assert assessment.passed is False


def test_quality_gate_requires_semantic_review_for_long_contrastive_dialogue():
    from src.pipeline.quality import TranslationQualityGate

    source = (
        "In the past it was difficult to take their money, but now they are "
        "ordinary people so it should be easy to loot them."
    )
    thai = (
        "เมื่อก่อนเอาเงินจากพวกเขาได้ยาก แต่ตอนนี้พวกเขาเป็นคนธรรมดาแล้ว "
        "จึงน่าจะปล้นได้ง่าย"
    )

    assessment = TranslationQualityGate().evaluate(_segment(source), thai, glossary=())

    assert assessment.requires_semantic_review is True


def test_quality_gate_detects_single_letter_english_dialogue_but_allows_source_rank_letters():
    from src.pipeline.quality import TranslationQualityGate

    gate = TranslationQualityGate()

    leakage = gate.evaluate(_segment("I!"), "I!", glossary=())
    rank = gate.evaluate(_segment("She reached Rank A."), "เธอขึ้นถึงระดับ A แล้ว", glossary=())

    assert "ENGLISH_LEAKAGE" in leakage.issue_codes
    assert "ENGLISH_LEAKAGE" not in rank.issue_codes


def test_quality_gate_accepts_a_short_complete_translation_without_semantic_review():
    from src.pipeline.quality import TranslationQualityGate

    assessment = TranslationQualityGate().evaluate(
        _segment("Close the door."),
        "ปิดประตูด้วย",
        glossary=(),
    )

    assert assessment.passed is True
    assert assessment.issue_codes == ()
    assert assessment.requires_semantic_review is False


@pytest.mark.parametrize(
    ("source", "thai"),
    [
        (
            "He waited for the sweet point to strike.",
            "เขารอจังหวะที่เหมาะสมเพื่อโจมตี",
        ),
        (
            "Now give me some sweet points, isn't this what teams are for?",
            "ทีนี้ส่งแต้มหวานๆ มาให้ฉันบ้างสิ นี่ไม่ใช่ประโยชน์ของการอยู่ทีมเดียวกันหรอกเหรอ?",
        ),
    ],
)
def test_quality_gate_routes_sweet_points_to_contextual_semantic_review(source, thai):
    from src.pipeline.quality import TranslationQualityGate

    assessment = TranslationQualityGate().evaluate(
        _segment(source),
        thai,
        glossary=(),
    )

    assert "AMBIGUOUS_TERM_REVIEW" in assessment.issue_codes
    assert "SEMANTIC_OMISSION" not in assessment.issue_codes
    assert assessment.passed is False
    assert assessment.requires_semantic_review is True


def test_batch_gate_rejects_missing_or_extra_segment_results():
    from src.pipeline.quality import TranslationQualityGate

    segments = (_segment("One", segment_id="1:1"), _segment("Two", segment_id="1:2"))

    missing = TranslationQualityGate().evaluate_batch(
        segments,
        {"1:1": "หนึ่ง"},
        glossary=(),
    )
    extra = TranslationQualityGate().evaluate_batch(
        segments,
        {"1:1": "หนึ่ง", "1:2": "สอง", "1:3": "สาม"},
        glossary=(),
    )

    assert "RESULT_COUNT_MISMATCH" in missing.issue_codes
    assert "RESULT_COUNT_MISMATCH" in extra.issue_codes
    assert missing.passed is False
    assert extra.passed is False


def _semantic_fixture_failures(case, translated_text):
    missing = [
        alternatives
        for alternatives in case["required_meanings"]
        if not any(term in translated_text for term in alternatives)
    ]
    forbidden = [
        term for term in case["forbidden_meanings"] if term in translated_text
    ]
    return missing, forbidden


def test_chapter_153_reference_preserves_all_meanings_without_hallucinated_fighting():
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = cases[0]

    missing, forbidden = _semantic_fixture_failures(case, case["reference_translation"])

    assert missing == []
    assert forbidden == []


def test_chapter_153_current_translation_is_caught_as_a_semantic_regression():
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    case = cases[0]

    missing, forbidden = _semantic_fixture_failures(case, case["bad_translation"])

    assert ["ตอนนี้", "ตอนนี้พวกเขา"] in missing
    assert ["คนธรรมดา"] in missing
    assert ["ง่าย"] in missing
    assert "สู้รบ" in forbidden


def test_chapter_153_regression_is_routed_to_semantic_review():
    from src.pipeline.quality import TranslationQualityGate

    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    assessment = TranslationQualityGate().evaluate(
        _segment(case["source_text"], segment_id=case["segment_id"]),
        case["bad_translation"],
        glossary=(
            {"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},
        ),
    )

    assert assessment.passed is False
    assert assessment.requires_semantic_review is True
    assert {"TIMELINE_MISMATCH", "LENGTH_RATIO_OUTLIER"} & set(assessment.issue_codes)
