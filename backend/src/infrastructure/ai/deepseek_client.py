import asyncio
import httpx
import json
from typing import Dict, Any, List, Optional
from src.config import settings
from src.infrastructure.ai.groq_client import CompletionResult

# Global semaphores separated by model tier with safety headroom (well below 2500 and 500 RPM limits)
_deepseek_flash_semaphore = asyncio.Semaphore(8)
_deepseek_pro_semaphore = asyncio.Semaphore(3)

# Shared keep-alive HTTP client to eliminate TCP+TLS handshake overhead per request
_shared_http_client: Optional[httpx.AsyncClient] = None


def _get_shared_http_client(timeout_seconds: float) -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
        _shared_http_client = httpx.AsyncClient(timeout=timeout_seconds, limits=limits)
    return _shared_http_client


class DeepSeekClient:
    """
    Authoritative client for official DeepSeek API (V4 models).
    Strictly isolated from GroqClient with no cross-provider fallback.

    Model mapping per official DeepSeek docs (api-docs.deepseek.com/quick_start/pricing):

    ┌─────────────────────┬──────────────────────────────┬──────────────────────┐
    │ Provider name       │ Actual API model             │ Cost (input/output)  │
    ├─────────────────────┼──────────────────────────────┼──────────────────────┤
    │ deepseek-v4-flash   │ deepseek-v4-flash            │ $0.003625 / $0.28    │
    │ deepseek-v4-pro     │ deepseek-v4-pro              │ $0.435 / $0.87       │
    │ deepseek-chat       │ deepseek-v4-flash (compat)   │ $0.003625 / $0.28    │
    └─────────────────────┴──────────────────────────────┴──────────────────────┘

    Note: deepseek-chat and deepseek-reasoner will be deprecated on 2026-07-24.
    They correspond to non-thinking and thinking modes of deepseek-v4-flash.
    """

    MODEL_MAPPINGS = {
        "deepseek-v4-flash": "deepseek-v4-flash",
        "deepseek-v4-pro": "deepseek-v4-pro",
        "deepseek-chat": "deepseek-v4-flash",  # legacy compat → flash non-thinking
    }

    # Whether the underlying API model supports response_format json_object
    _SUPPORTS_JSON_FORMAT = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})

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

    def _get_semaphore(self) -> asyncio.Semaphore:
        if self.model in ("deepseek-v4-flash", "deepseek-chat"):
            return _deepseek_flash_semaphore
        return _deepseek_pro_semaphore

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
        semaphore = self._get_semaphore()
        client = _get_shared_http_client(self.timeout_seconds)
        async with semaphore:
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

