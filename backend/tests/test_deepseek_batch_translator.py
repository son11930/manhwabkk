import pytest
from unittest.mock import AsyncMock

from src.infrastructure.ai.groq_client import CompletionResult
from src.pipeline.contracts import OCRSegment
from src.pipeline.deepseek_batch_translator import DeepSeekBatchTranslator, calculate_deepseek_cost_usd, group_pages_for_batching


def _make_page_segments(page_idx: int, num_segments: int = 5) -> list[OCRSegment]:
    return [
        OCRSegment(f"{page_idx}:{item}", page_idx, item, (10, 10, 100, 100), (f"Page {page_idx} Text {item}",), f"Page {page_idx} Text {item}", 0.99)
        for item in range(1, num_segments + 1)
    ]


def test_group_pages_into_batches_up_to_5_pages():
    batches = group_pages_for_batching([_make_page_segments(page) for page in range(1, 13)])
    assert [len(batch) for batch in batches] == [5, 5, 2]


def test_group_pages_respects_max_segments_limit():
    batches = group_pages_for_batching([_make_page_segments(page, 30) for page in range(1, 6)])
    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_cost_calculation_for_deepseek_models():
    assert calculate_deepseek_cost_usd("deepseek-v4-flash", 1_000_000, 1_000_000) == pytest.approx(0.283625)
    assert calculate_deepseek_cost_usd("deepseek-v4-pro", 1_000_000, 1_000_000) == pytest.approx(1.305)


@pytest.mark.asyncio
async def test_translate_multipage_batch_uses_each_segment_once():
    client = AsyncMock()
    client.model = "deepseek-v4-flash"
    client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": [{"segment_id": "1:1", "text": "one"}, {"segment_id": "2:1", "text": "two"}]}',
        model="deepseek-v4-flash", attempts=1, prompt_tokens=500, completion_tokens=200, total_tokens=700,
    )
    result = await DeepSeekBatchTranslator(client).translate_page_batch([_make_page_segments(1, 1), _make_page_segments(2, 1)])
    assert result.translations == {"1:1": "one", "2:1": "two"}
    user_message = client.generate_chat_completion_result.call_args.kwargs["messages"][1]["content"]
    assert '"page_markers"' not in user_message
    assert user_message.count('"segment_id": "1:1"') == 1
    assert user_message.count('"segment_id": "2:1"') == 1


@pytest.mark.asyncio
async def test_incomplete_batch_never_returns_source_as_translation():
    client = AsyncMock()
    client.model = "deepseek-v4-flash"
    client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": []}', model="deepseek-v4-flash", attempts=1, prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        await DeepSeekBatchTranslator(client).translate_page_batch([_make_page_segments(1, 1)])
