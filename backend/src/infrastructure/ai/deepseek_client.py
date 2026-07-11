import asyncio
import httpx
import json
from typing import Dict, Any, List, Optional
from src.config import settings
from src.infrastructure.ai.groq_client import CompletionResult

# Global semaphore for DeepSeek API calls
_deepseek_semaphore = asyncio.Semaphore(3)


class DeepSeekClient:
    """
    Authoritative client for official DeepSeek API (deepseek-chat / deepseek-reasoner).
    Strictly isolated from GroqClient with no cross-provider fallback.
    """

    MODEL_MAPPINGS = {
        "deepseek-v4-flash": "deepseek-v4-flash",
        "deepseek-v4-pro": "deepseek-reasoner",
        "deepseek-chat": "deepseek-chat",
    }

    def __init__(
        self,
        provider: str = "deepseek-v4-flash",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_retries: Optional[int] = None,
    ):
        raw_key = api_key if api_key is not None else settings.DEEPSEEK_API_KEY
        if not raw_key or not raw_key.strip():
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not configured. Please set DEEPSEEK_API_KEY in environment variables."
            )
        self.api_key = raw_key.strip()
        self.base_url = base_url or settings.DEEPSEEK_API_BASE_URL
        self.max_retries = max_retries if max_retries is not None else settings.DEEPSEEK_MAX_RETRIES
        self.timeout_seconds = settings.DEEPSEEK_TIMEOUT_SECONDS
        self.provider = provider
        self.model = self.MODEL_MAPPINGS.get(provider, "deepseek-chat")

    async def generate_chat_completion_result(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 650,
    ) -> CompletionResult:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Request JSON format output when supported
        if self.model != "deepseek-reasoner":
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        attempts = 0
        async with _deepseek_semaphore:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                while attempts < self.max_retries:
                    attempts += 1
                    try:
                        response = await client.post(
                            self.base_url,
                            headers=headers,
                            json=payload,
                        )
                        response.raise_for_status()
                        data = response.json()

                        choice = data.get("choices", [{}])[0]
                        message = choice.get("message", {})
                        content = message.get("content", "") or ""

                        usage_data = data.get("usage", {})
                        prompt_tokens = int(usage_data.get("prompt_tokens", 0))
                        completion_tokens = int(usage_data.get("completion_tokens", 0))
                        total_tokens = int(usage_data.get("total_tokens", prompt_tokens + completion_tokens))

                        return CompletionResult(
                            text=content.strip(),
                            model=self.model,
                            attempts=attempts,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=total_tokens,
                        )
                    except (httpx.HTTPStatusError, httpx.RequestError) as e:
                        is_retryable = False
                        if isinstance(e, httpx.HTTPStatusError):
                            if e.response.status_code in [429, 500, 502, 503, 504]:
                                is_retryable = True
                        elif isinstance(e, httpx.RequestError):
                            is_retryable = True

                        if attempts < self.max_retries and is_retryable:
                            await asyncio.sleep(2 ** attempts)
                            continue
                        raise

        raise RuntimeError(f"DeepSeek API call failed after {attempts} attempts.")

    async def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 650,
    ) -> str:
        res = await self.generate_chat_completion_result(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return res.text

