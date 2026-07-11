import json
import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image


def _make_segment(**overrides):
    from src.pipeline.contracts import OCRSegment

    values = {
        "segment_id": "7:1",
        "page_index": 7,
        "reading_order": 1,
        "box": (720, 645, 1110, 820),
        "raw_lines": (
            "IN THE PAST, IT WAS EITHER STUDENTS OR DRAGNET.",
            "I HAD A HARD TIME GRABBING THEIR MONEY.",
        ),
        "source_text": (
            "In the past, it was either students or Dragnet. "
            "I had a hard time grabbing their money."
        ),
        "confidence": 0.83,
    }
    values.update(overrides)
    return OCRSegment(**values)


def test_ocr_segment_keeps_stable_identity_and_ocr_evidence():
    segment = _make_segment()

    assert segment.segment_id == "7:1"
    assert segment.page_index == 7
    assert segment.reading_order == 1
    assert segment.box == (720, 645, 1110, 820)
    assert segment.raw_lines[1] == "I HAD A HARD TIME GRABBING THEIR MONEY."
    assert segment.source_text.endswith("their money.")
    assert segment.confidence == pytest.approx(0.83)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_ocr_segment_rejects_confidence_outside_probability_range(confidence):
    with pytest.raises(ValueError):
        _make_segment(confidence=confidence)


def test_ocr_engine_emits_structured_segments_with_grouped_raw_line_evidence():
    from src.pipeline.ocr import MangaOCREngine

    image = Image.new("RGB", (300, 300), color="white")
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="JPEG")
    engine = MangaOCREngine.__new__(MangaOCREngine)
    engine.is_ready = True
    engine.ocr_engine = lambda _image: (
        [
            (
                ((20, 20), (200, 20), (200, 45), (20, 45)),
                "FIRST LINE",
                0.91,
            ),
            (
                ((22, 48), (198, 48), (198, 73), (22, 73)),
                "SECOND LINE",
                0.73,
            ),
        ],
        None,
    )

    segments = engine.detect_and_extract_sync(image_bytes.getvalue(), page_index=7)

    assert len(segments) == 1
    assert segments[0].segment_id == "7:1"
    assert segments[0].page_index == 7
    assert segments[0].reading_order == 1
    assert segments[0].raw_lines == ("FIRST LINE", "SECOND LINE")
    assert segments[0].source_text == "FIRST LINE SECOND LINE"
    assert segments[0].confidence == pytest.approx(0.73)
    assert segments[0].box == (20, 20, 200, 73)


def test_translation_batch_request_is_immutable_and_limits_rolling_context_to_eight():
    from src.pipeline.contracts import TranslationBatchRequest

    segment = _make_segment()
    context = tuple(
        {
            "segment_id": f"6:{index}",
            "source_text": f"Previous source {index}",
            "final_thai": f"บริบทก่อนหน้า {index}",
        }
        for index in range(1, 9)
    )
    request = TranslationBatchRequest(
        segments=(segment,),
        profile={"genre": "neutral", "style": {"register": "conversational"}},
        glossary=(
            {"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},
        ),
        context=context,
    )

    assert len(request.context) == 8
    assert request.glossary[0]["locked"] is True
    with pytest.raises((AttributeError, TypeError, ValueError)):
        request.profile = {"genre": "modern_cultivation"}

    with pytest.raises(ValueError):
        TranslationBatchRequest(
            segments=(segment,),
            profile={"genre": "neutral"},
            glossary=(),
            context=context + (context[-1],),
        )


def test_translation_result_preserves_draft_final_model_attempts_and_qc_evidence():
    from src.pipeline.contracts import TranslationResult

    result = TranslationResult(
        segment_id="7:1",
        source_text="Dragnet is here.",
        draft_thai="พวกแดร็กเน็ตมาแล้ว",
        final_thai="เครือข่ายสวรรค์มาแล้ว",
        model="llama-3.3-70b-versatile",
        attempts=2,
        qc_status="APPROVED",
        issue_codes=("LOCKED_TERM_CORRECTED",),
    )

    assert result.source_text == "Dragnet is here."
    assert result.draft_thai != result.final_thai
    assert result.model == "llama-3.3-70b-versatile"
    assert result.attempts == 2
    assert result.qc_status == "APPROVED"
    assert result.issue_codes == ("LOCKED_TERM_CORRECTED",)


def test_json_parser_maps_by_segment_id_and_preserves_multiline_text():
    from src.pipeline.translator import parse_translation_response

    response = json.dumps(
        {
            "translations": [
                {"segment_id": "7:2", "text": "ลาก่อน"},
                {
                    "segment_id": "7:1",
                    "text": "ประโยคแรก\nประโยคที่สองยังต้องอยู่ครบ",
                },
            ]
        },
        ensure_ascii=False,
    )

    parsed = parse_translation_response(response, expected_segment_ids=("7:1", "7:2"))

    assert tuple(parsed) == ("7:1", "7:2")
    assert parsed["7:1"] == "ประโยคแรก\nประโยคที่สองยังต้องอยู่ครบ"
    assert parsed["7:2"] == "ลาก่อน"


@pytest.mark.parametrize(
    "payload",
    [
        {"translations": [{"segment_id": "7:1", "text": "หนึ่ง"}]},
        {
            "translations": [
                {"segment_id": "7:1", "text": "หนึ่ง"},
                {"segment_id": "7:1", "text": "ซ้ำ"},
                {"segment_id": "7:2", "text": "สอง"},
            ]
        },
        {
            "translations": [
                {"segment_id": "7:1", "text": "หนึ่ง"},
                {"segment_id": "7:3", "text": "เกินมา"},
            ]
        },
    ],
    ids=("missing-id", "duplicate-id", "unexpected-id"),
)
def test_json_parser_rejects_any_non_bijective_segment_mapping(payload):
    from src.pipeline.translator import TranslationResponseError, parse_translation_response

    with pytest.raises(TranslationResponseError):
        parse_translation_response(
            json.dumps(payload, ensure_ascii=False),
            expected_segment_ids=("7:1", "7:2"),
        )


@pytest.mark.parametrize(
    "response",
    [
        "[1] ข้อความแบบเก่าที่ไม่ใช่ JSON",
        '{"translations": [{"segment_id": "7:1", "text": "ถูกตัดท้าย"}',
        "",
    ],
    ids=("legacy-numbered-text", "truncated-json", "empty-response"),
)
def test_json_parser_rejects_malformed_or_truncated_responses(response):
    from src.pipeline.translator import TranslationResponseError, parse_translation_response

    with pytest.raises(TranslationResponseError):
        parse_translation_response(response, expected_segment_ids=("7:1",))


@pytest.mark.asyncio
async def test_translator_propagates_profile_locked_glossary_and_last_eight_context_items():
    from src.infrastructure.ai.groq_client import CompletionResult
    from src.pipeline.contracts import TranslationBatchRequest
    from src.pipeline.translator import AITranslatorEngine

    client = AsyncMock()
    client.generate_chat_completion.return_value = CompletionResult(
        text=json.dumps(
            {
                "translations": [
                    {"segment_id": "7:1", "text": "เครือข่ายสวรรค์มาแล้ว"}
                ]
            },
            ensure_ascii=False,
        ),
        model="llama-3.3-70b-versatile",
        attempts=1,
    )
    request = TranslationBatchRequest(
        segments=(_make_segment(source_text="Dragnet is here."),),
        profile={"genre": "neutral", "style": {"register": "conversational"}},
        glossary=(
            {"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},
        ),
        context=tuple(
            {
                "segment_id": f"6:{index}",
                "source_text": f"Previous source {index}",
                "final_thai": f"บริบทก่อนหน้า {index}",
            }
            for index in range(1, 9)
        ),
    )
    translator = AITranslatorEngine(client=client)

    results = await translator.translate_batch(request)

    assert len(results) == 1
    assert results[0].segment_id == "7:1"
    assert results[0].final_thai == "เครือข่ายสวรรค์มาแล้ว"
    assert results[0].model == "llama-3.3-70b-versatile"
    sent_messages = client.generate_chat_completion.await_args.kwargs["messages"]
    serialized_prompt = "\n".join(message["content"] for message in sent_messages)
    assert '"segment_id": "7:1"' in serialized_prompt
    assert "Dragnet" in serialized_prompt
    assert "เครือข่ายสวรรค์" in serialized_prompt
    assert '"locked": true' in serialized_prompt
    assert "Previous source 1" in serialized_prompt
    assert "บริบทก่อนหน้า 8" in serialized_prompt
    assert "modern_cultivation" not in serialized_prompt


@pytest.mark.asyncio
async def test_translate_batch_keeps_the_veteran_prompt_and_proven_payload_schema():
    from src.infrastructure.ai.groq_client import CompletionResult
    from src.pipeline.contracts import TranslationBatchRequest
    from src.pipeline.translator import AITranslatorEngine

    client = AsyncMock()
    client.generate_chat_completion.return_value = CompletionResult(
        text=json.dumps(
            {"translations": [{"id": "7:1", "th": "เครือข่ายสวรรค์มาถึงแล้ว"}]},
            ensure_ascii=False,
        ),
        model="llama-3.3-70b-versatile",
        attempts=1,
    )
    request = TranslationBatchRequest(
        segments=(_make_segment(source_text="Dragnet is here."),),
        profile={"genre": "neutral", "quality_review": "Fix only the flagged issue.", "draft_text": "เครือข่ายมาแล้ว", "quality_issue_codes": ("GLOSSARY_MISMATCH",)},
        glossary=({"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True},),
        context=tuple(
            {
                "segment_id": f"6:{index}",
                "source_text": f"Previous source {index}",
                "final_thai": f"บริบทก่อนหน้า {index}",
            }
            for index in range(1, 9)
        ),
    )

    translator = AITranslatorEngine(client=client)
    results = await translator.translate_batch(request)

    assert results[0].final_thai == "เครือข่ายสวรรค์มาถึงแล้ว"
    messages = client.generate_chat_completion.await_args.kwargs["messages"]
    payload = json.loads(messages[1]["content"])
    assert payload["segments"] == [{"segment_id": "7:1", "id": "7:1", "text": "Dragnet is here."}]
    assert payload["glossary"] == [{"source": "Dragnet", "thai": "เครือข่ายสวรรค์", "locked": True}]
    assert len(payload["context"]) == 8
    assert payload["context"][0]["source_text"] == "Previous source 1"
    assert payload["genre"] == "neutral"
    assert payload["quality_review"] == {
        "draft_thai": "เครือข่ายมาแล้ว",
        "issue_codes": ["GLOSSARY_MISMATCH"],
        "instruction": "Fix only the flagged issue.",
    }
    assert messages[0]["content"].startswith(translator.system_prompt)
    assert "CRITICAL SCENE COHESION & JSON FORMAT" in messages[0]["content"]
    assert "context-sensitive" in messages[0]["content"]


@pytest.mark.asyncio
async def test_translate_batch_preserves_partial_batch_and_fills_missing():
    from src.pipeline.translator import AITranslatorEngine
    from src.pipeline.contracts import TranslationBatchRequest

    client = AsyncMock()
    # Attempt 1: returns invalid JSON to trigger retry
    # Attempt 2: returns partial batch (only 1:1, missing 1:2)
    client.generate_chat_completion.side_effect = [
        "not json",
        json.dumps({"translations": [{"segment_id": "1:1", "text": "แปลข้อความ 1"}]}),
        "แปลเติมข้อความ 2",  # For the single fallback call on missing 1:2
    ]

    request = TranslationBatchRequest(
        segments=(
            _make_segment(segment_id="1:1", source_text="Hello 1"),
            _make_segment(segment_id="1:2", source_text="Hello 2"),
        ),
        profile={"genre": "modern_cultivation"},
    )
    translator = AITranslatorEngine(client=client)

    results = await translator.translate_batch(request)

    assert len(results) == 2
    assert results[0].segment_id == "1:1"
    assert results[0].final_thai == "แปลข้อความ 1"
    assert results[1].segment_id == "1:2"
    assert results[1].final_thai == "แปลเติมข้อความ 2"
    assert client.generate_chat_completion.call_count == 3
