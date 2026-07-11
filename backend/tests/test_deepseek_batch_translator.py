import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.contracts import OCRSegment
from src.pipeline.deepseek_batch_translator import (
    DeepSeekBatchTranslator,
    group_pages_for_batching,
    calculate_deepseek_cost_usd,
)
from src.infrastructure.ai.groq_client import CompletionResult


def _make_page_segments(page_idx: int, num_segments: int = 5) -> list[OCRSegment]:
    segs = []
    for i in range(1, num_segments + 1):
        segs.append(
            OCRSegment(
                segment_id=f"{page_idx}:{i}",
                page_index=page_idx,
                reading_order=i,
                box=(10, 10, 100, 100),
                raw_lines=(f"Page {page_idx} Text {i}",),
                source_text=f"Page {page_idx} Text {i}",
                confidence=0.99,
            )
        )
    return segs


def test_group_pages_into_batches_up_to_5_pages():
    pages = [_make_page_segments(p, 5) for p in range(1, 13)]  # 12 pages total
    batches = group_pages_for_batching(pages, max_pages=5, max_segments=80, max_chars=120000)
    assert len(batches) == 3
    assert len(batches[0]) == 5  # Pages 1..5
    assert len(batches[1]) == 5  # Pages 6..10
    assert len(batches[2]) == 2  # Pages 11..12


def test_group_pages_respects_max_segments_limit():
    # Each page has 30 segments. 5 pages would be 150 segments (> 80 limit)
    pages = [_make_page_segments(p, 30) for p in range(1, 6)]
    batches = group_pages_for_batching(pages, max_pages=5, max_segments=80, max_chars=120000)
    # 30 segments per page -> max 2 pages per batch (60 segments <= 80)
    assert len(batches) == 3
    assert len(batches[0]) == 2
    assert len(batches[1]) == 2
    assert len(batches[2]) == 1


def test_cost_calculation_for_deepseek_models():
    cost_flash = calculate_deepseek_cost_usd("deepseek-v4-flash", 1_000_000, 1_000_000)
    assert cost_flash == pytest.approx(0.28 + 0.56)

    cost_chat = calculate_deepseek_cost_usd("deepseek-chat", 1_000_000, 1_000_000)
    assert cost_chat == pytest.approx(0.14 + 0.28)

    cost_pro = calculate_deepseek_cost_usd("deepseek-v4-pro", 1_000_000, 1_000_000)
    assert cost_pro == pytest.approx(0.55 + 2.19)


@pytest.mark.asyncio
async def test_translate_multipage_batch():
    mock_client = AsyncMock()
    mock_client.model = "deepseek-chat"
    mock_client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": [{"segment_id": "1:1", "text": "แปลหน้า1"}, {"segment_id": "2:1", "text": "แปลหน้า2"}]}',
        model="deepseek-chat",
        attempts=1,
        prompt_tokens=500,
        completion_tokens=200,
        total_tokens=700,
    )

    batch_translator = DeepSeekBatchTranslator(client=mock_client, provider="deepseek-v4-flash")
    pages = [
        _make_page_segments(1, 1),
        _make_page_segments(2, 1),
    ]

    result = await batch_translator.translate_page_batch(pages, glossary=(), context=())
    assert result.translations == {"1:1": "แปลหน้า1", "2:1": "แปลหน้า2"}
    assert result.input_tokens == 500
    assert result.output_tokens == 200
    assert result.cost_usd > 0.0

    # Ensure prompt contained page markers
    calls = mock_client.generate_chat_completion_result.call_args_list
    messages = calls[0].kwargs["messages"]
    user_msg = messages[1]["content"]
    assert "=== หน้า 1 ===" in user_msg
    assert "=== หน้า 2 ===" in user_msg
