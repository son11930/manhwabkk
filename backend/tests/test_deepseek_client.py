import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from src.infrastructure.ai.deepseek_client import DeepSeekClient
from src.infrastructure.ai.groq_client import CompletionResult


def test_deepseek_model_mapping():
    c1 = DeepSeekClient(provider="deepseek-v4-flash", api_key="test-key")
    assert c1.model == "deepseek-v4-flash"

    c2 = DeepSeekClient(provider="deepseek-v4-pro", api_key="test-key")
    assert c2.model == "deepseek-v4-pro"

    c3 = DeepSeekClient(provider="deepseek-chat", api_key="test-key")
    assert c3.model == "deepseek-v4-flash"


def test_deepseek_missing_api_key_raises_safe_error():
    with pytest.raises(RuntimeError) as exc_info:
        DeepSeekClient(provider="deepseek-v4-flash", api_key="")
    assert "DEEPSEEK_API_KEY is not configured" in str(exc_info.value)
    # Ensure no secrets leak in exception
    assert "secret" not in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_deepseek_successful_completion():
    client = DeepSeekClient(provider="deepseek-v4-flash", api_key="test-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"translated_text": "สวัสดี"}'}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await client.generate_chat_completion_result(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.3,
            max_tokens=650,
        )

        assert isinstance(result, CompletionResult)
        assert result.text == '{"translated_text": "สวัสดี"}'
        assert result.model == "deepseek-v4-flash"
        assert result.attempts == 1
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150


@pytest.mark.asyncio
async def test_deepseek_retry_on_server_error_no_fallback_to_groq():
    client = DeepSeekClient(provider="deepseek-v4-flash", api_key="test-key", max_retries=2)
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 500
    error_response = httpx.Response(500, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"))
    mock_resp_fail.raise_for_status.side_effect = httpx.HTTPStatusError("500 Server Error", request=error_response.request, response=error_response)

    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.json.return_value = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    mock_resp_success.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [mock_resp_fail, mock_resp_success]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await client.generate_chat_completion_result(
                messages=[{"role": "user", "content": "test"}],
            )
            assert result.attempts == 2
            assert result.model == "deepseek-v4-flash"
            assert {call.kwargs["json"]["model"] for call in mock_post.call_args_list} == {"deepseek-v4-flash"}


def test_deepseek_separate_semaphores_and_pooling():
    from src.infrastructure.ai.deepseek_client import (
        _deepseek_flash_semaphore,
        _deepseek_pro_semaphore,
        _get_shared_http_client,
    )
    assert _deepseek_flash_semaphore._value == 8
    assert _deepseek_pro_semaphore._value == 3

    flash_client = DeepSeekClient(provider="deepseek-v4-flash", api_key="test-key")
    assert flash_client._get_semaphore() is _deepseek_flash_semaphore

    pro_client = DeepSeekClient(provider="deepseek-v4-pro", api_key="test-key")
    assert pro_client._get_semaphore() is _deepseek_pro_semaphore

    http_c1 = _get_shared_http_client(30.0)
    http_c2 = _get_shared_http_client(30.0)
    assert http_c1 is http_c2
