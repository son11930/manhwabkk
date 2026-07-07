from typing import Optional
from src.infrastructure.ai.groq_client import GroqClient

class AITranslatorEngine:
    """
    AI Translator Engine powered by Groq API (Llama-3 / Mixtral).
    Uses specialized prompt engineering for natural Thai manga/manhua translation.
    """
    def __init__(self, client: Optional[GroqClient] = None):
        self.client = client or GroqClient()
        self.system_prompt = (
            "คุณคือนักแปลการ์ตูนมังฮวาและมังฮัวจากภาษาอังกฤษเป็นภาษาไทยระดับมืออาชีพ "
            "สำนวนของคุณสนุก ดุดัน เข้ากับบริบทแฟนตาซี แอคชั่น หรือโรแมนติก "
            "แปลให้เหมือนคนแปลจริงๆ ไม่ใช่โปรแกรมแปลภาษา และห้ามมีคำอธิบายเพิ่มเติมใดๆ นอกเหนือจากข้อความที่แปลแล้ว"
        )

    async def translate_text(self, text: str, target_lang: str = "th", context: Optional[str] = None) -> str:
        """
        Translates text into natural Thai webtoon dialect.
        """
        if not text or not text.strip():
            return ""

        user_content = f"Translate the following manga speech bubble text into Thai:\n\n{text}"
        if context:
            user_content += f"\n\nContext/Slang guidance: {context}"

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content}
        ]

        return await self.client.generate_chat_completion(messages=messages, temperature=0.3)
