from typing import Dict, Any, List
import httpx
from src.config import settings

class GroqClient:
    """
    HTTP client wrapper for Groq AI API (Llama-3.3-70b-versatile / Mixtral).
    """
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    async def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1024
    ) -> str:
        """
        Sends chat completion request to Groq API and returns translated text.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
