import pytest
from unittest.mock import AsyncMock
from src.pipeline.translator import AITranslatorEngine
from src.pipeline.contracts import TranslationBatchRequest, OCRSegment
from src.infrastructure.ai.deepseek_client import DeepSeekClient
from src.infrastructure.ai.groq_client import CompletionResult


def _make_segment(segment_id: str = "1:1", source_text: str = "Hello", page_index: int = 0, reading_order: int = 1) -> OCRSegment:
    return OCRSegment(
        segment_id=segment_id,
        page_index=page_index,
        reading_order=reading_order,
        box=(10, 10, 100, 100),
        raw_lines=(source_text,),
        source_text=source_text,
        confidence=0.99,
    )


@pytest.mark.asyncio
async def test_translator_uses_deepseek_client_and_returns_completion_result():
    client = AsyncMock(spec=DeepSeekClient)
    client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": [{"segment_id": "1:1", "text": "สวัสดี"}, {"segment_id": "1:2", "text": "โลก"}]}',
        model="deepseek-chat",
        attempts=1,
        prompt_tokens=120,
        completion_tokens=40,
        total_tokens=160,
    )

    request = TranslationBatchRequest(
        segments=(
            _make_segment("1:1", "Hello"),
            _make_segment("1:2", "World"),
        ),
        profile={"genre": "modern_cultivation"},
    )
    translator = AITranslatorEngine(client=client)
    res = await translator.translate_batch(request)
    assert isinstance(res, list)
    assert len(res) == 2
    assert res[0].segment_id == "1:1"
    assert res[0].final_thai == "สวัสดี"
    assert res[0].model == "deepseek-chat"
    assert res[1].segment_id == "1:2"
    assert res[1].final_thai == "โลก"
    assert client.generate_chat_completion_result.called
