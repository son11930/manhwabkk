import pytest
from src.infrastructure.ai.factory import get_ai_client
from src.infrastructure.ai.groq_client import GroqClient
from src.infrastructure.ai.deepseek_client import DeepSeekClient


def test_get_ai_client_factory():
    c_groq = get_ai_client("groq")
    assert isinstance(c_groq, GroqClient)

    c_flash = get_ai_client("deepseek-v4-flash", api_key="test-key")
    assert isinstance(c_flash, DeepSeekClient)
    assert c_flash.model == "deepseek-chat"

    c_pro = get_ai_client("deepseek-v4-pro", api_key="test-key")
    assert isinstance(c_pro, DeepSeekClient)
    assert c_pro.model == "deepseek-reasoner"

    c_chat = get_ai_client("deepseek-chat", api_key="test-key")
    assert isinstance(c_chat, DeepSeekClient)
    assert c_chat.model == "deepseek-chat"
