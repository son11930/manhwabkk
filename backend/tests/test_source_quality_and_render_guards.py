from __future__ import annotations

from pathlib import Path

import pytest

from src.pipeline.contracts import OCRSegment
from src.pipeline.ocr import MangaOCREngine
from src.pipeline.rendering import (
    RenderInstruction,
    associate_shifted_region_candidates,
    build_render_instructions,
    deduplicate_render_instructions,
)
from src.pipeline.source_quality import OCRCandidate, select_source_candidate


def _candidate(text: str, confidence: float, *, transform: str = "base") -> OCRCandidate:
    return OCRCandidate(
        text=text,
        confidence=confidence,
        transform_id=transform,
        box=(10, 10, 100, 40),
        coverage=1.0,
    )


def test_source_selector_prefers_complete_consensus_over_higher_confidence_ocr_garbage():
    selected = select_source_candidate(
        (
            _candidate("THIRTY-FINE", 0.91, transform="base"),
            _candidate("THIRTY-FIVE", 0.86, transform="roi-shear"),
            _candidate("THIRTY-FIVE", 0.84, transform="roi-contrast"),
        )
    )

    assert selected.text == "THIRTY-FIVE"


def test_source_selector_flags_suspicious_alpha_numeric_source_when_no_evidence_can_repair_it():
    selected = select_source_candidate((_candidate("OHS 01 PLEASE HELP ME", 0.95),))

    assert "OCR_SUSPECT_ALNUM" in selected.issue_codes


def test_render_builder_rejects_duplicate_region_before_pixel_writes():
    with pytest.raises(ValueError, match="duplicate region"):
        build_render_instructions((
            RenderInstruction("page-1:region-a", (10, 10, 100, 60), "หนึ่ง"),
            RenderInstruction("page-1:region-a", (10, 10, 100, 60), "สอง"),
        ))


def test_render_builder_preserves_adjacent_distinct_bubbles_even_when_text_matches():
    instructions = build_render_instructions((
        RenderInstruction("page-1:left", (10, 10, 110, 80), "สวัสดี"),
        RenderInstruction("page-1:right", (130, 10, 230, 80), "สวัสดี"),
    ))

    assert [item.region_id for item in instructions] == ["page-1:left", "page-1:right"]


def test_render_builder_deduplicates_only_the_same_stable_region():
    instructions = deduplicate_render_instructions((
        RenderInstruction("bubble", (10, 10, 200, 200), "ข้อความหลัก"),
        RenderInstruction("bubble", (30, 40, 140, 100), "ข้อความซ้ำ"),
        RenderInstruction("nested-but-distinct", (30, 40, 140, 100), "บทพูดอีกอัน"),
    ))

    assert [item.region_id for item in instructions] == ["bubble", "nested-but-distinct"]


def test_shifted_duplicate_boxes_share_a_render_region_even_at_previous_bucket_boundary():
    associated = associate_shifted_region_candidates((
        RenderInstruction("first", (0, 10, 94, 104), "ต้นฉบับ"),
        RenderInstruction("shifted", (2, 12, 96, 106), "สำเนา"),
    ))
    assert [item.region_id for item in deduplicate_render_instructions(associated)] == ["first"]


def test_nearby_distinct_bubbles_are_not_collapsed_by_region_association():
    associated = associate_shifted_region_candidates((
        RenderInstruction("left", (10, 10, 100, 100), "ซ้าย"),
        RenderInstruction("right", (112, 10, 202, 100), "ขวา"),
    ))
    assert [item.region_id for item in associated] == ["left", "right"]


@pytest.mark.parametrize(
    ("fixture_name", "page_index", "expected"),
    (
        (
            "1.PNG",
            1,
            (
                "LU SHU'S VOICE!!",
                "LU SHU, PLEASE HELP ME TRANSLATE...",
                "EH, WHERE IS HE?",
            ),
        ),
        (
            "2.PNG",
            2,
            ("DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!",),
        ),
    ),
)
def test_italic_fixtures_emit_exact_verified_source_transcripts(fixture_name: str, page_index: int, expected: tuple[str, ...]):
    fixture = Path(__file__).resolve().parents[2] / "img" / fixture_name
    segments = MangaOCREngine().detect_and_extract_sync(fixture.read_bytes(), page_index=page_index)

    assert tuple(segment.source_text for segment in segments) == expected
