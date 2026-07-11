from typing import Optional, Any
from src.infrastructure.ai.groq_client import GroqClient
from src.infrastructure.ai.deepseek_client import DeepSeekClient


def get_ai_client(provider: str = "groq", api_key: Optional[str] = None, **kwargs: Any) -> Any:
    """
    Factory returning appropriate AI client for provider string:
    - 'groq' -> GroqClient
    - 'deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat' -> DeepSeekClient
    """
    provider_clean = (provider or "groq").lower().strip()
    if provider_clean == "groq":
        return GroqClient(api_key=api_key)
    elif provider_clean in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"):
        return DeepSeekClient(provider=provider_clean, api_key=api_key, **kwargs)
    else:
        raise ValueError(f"Unsupported translation provider: {provider}")
