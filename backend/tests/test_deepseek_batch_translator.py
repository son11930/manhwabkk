import pytest
from unittest.mock import AsyncMock

from src.infrastructure.ai.groq_client import CompletionResult
from src.pipeline.contracts import OCRSegment
from src.pipeline.deepseek_batch_translator import (
    DeepSeekBatchTranslator,
    append_batch_context,
    calculate_deepseek_cost_usd,
    group_pages_for_batching,
    parse_deepseek_batch_response,
)


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


def test_batch_context_carries_previous_final_thai_in_reading_order():
    previous = ({"segment_id": "0:1", "source_text": "Earlier", "final_thai": "ก่อนหน้า"},)
    context = append_batch_context(
        previous,
        [_make_page_segments(1, 2)],
        {"1:1": "เธอมาแล้ว", "1:2": "น้องสาวของเธอ"},
    )
    assert context == (
        {"segment_id": "0:1", "source_text": "Earlier", "final_thai": "ก่อนหน้า"},
        {"segment_id": "1:1", "source_text": "Page 1 Text 1", "final_thai": "เธอมาแล้ว"},
        {"segment_id": "1:2", "source_text": "Page 1 Text 2", "final_thai": "น้องสาวของเธอ"},
    )


def test_cost_calculation_for_deepseek_models():
    assert calculate_deepseek_cost_usd("deepseek-v4-flash", 1_000_000, 1_000_000) == pytest.approx(0.283625)
    assert calculate_deepseek_cost_usd("deepseek-v4-pro", 1_000_000, 1_000_000) == pytest.approx(1.305)


def test_partial_batch_parser_preserves_only_unambiguous_expected_ids():
    outcome = parse_deepseek_batch_response(
        '''{"translations": [
            {"id": "1:1", "th": "one"},
            {"id": "2:1", "th": "first"},
            {"id": "2:1", "th": "second"},
            {"id": "unknown", "th": "ignore"}
        ]}''',
        ("1:1", "2:1", "3:1"),
    )

    assert outcome.translations == {"1:1": "one"}
    assert outcome.missing_ids == ("2:1", "3:1")
    assert outcome.duplicate_ids == ("2:1",)
    assert outcome.unknown_ids == ("unknown",)
    assert outcome.parse_error is None


def test_partial_batch_parser_recovers_complete_entries_before_malformed_tail():
    outcome = parse_deepseek_batch_response(
        '{"translations": [{"id": "1:1", "th": "one"}, {"id": "2:1", "th": "two"},',
        ("1:1", "2:1", "3:1"),
    )

    assert outcome.translations == {"1:1": "one", "2:1": "two"}
    assert outcome.missing_ids == ("3:1",)
    assert outcome.duplicate_ids == ()
    assert outcome.unknown_ids == ()
    assert outcome.parse_error is not None


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
async def test_translate_batch_returns_valid_partial_result_with_missing_id_accounting():
    client = AsyncMock()
    client.model = "deepseek-v4-flash"
    client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": [{"segment_id": "1:1", "text": "one"}]}',
        model="deepseek-v4-flash", attempts=1, prompt_tokens=100, completion_tokens=50, total_tokens=150,
    )

    result = await DeepSeekBatchTranslator(client).translate_page_batch([_make_page_segments(1, 2)])

    assert result.translations == {"1:1": "one"}
    assert result.parse_outcome is not None
    assert result.parse_outcome.missing_ids == ("1:2",)


@pytest.mark.asyncio
async def test_incomplete_batch_never_returns_source_as_translation():
    client = AsyncMock()
    client.model = "deepseek-v4-flash"
    client.generate_chat_completion_result.return_value = CompletionResult(
        text='{"translations": []}', model="deepseek-v4-flash", attempts=1, prompt_tokens=1, completion_tokens=1, total_tokens=2,
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        await DeepSeekBatchTranslator(client).translate_page_batch([_make_page_segments(1, 1)])
