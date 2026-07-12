import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from src.pipeline.contracts import OCRSegment
from src.pipeline.translator import VETERAN_TRANSLATOR_SYSTEM_PROMPT, TranslationResponseError, parse_translation_response


@dataclass(frozen=True)
class BatchTranslationResult:
    translations: Dict[str, str]
    model: str
    attempts: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def calculate_deepseek_cost_usd(provider: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = (0.435, 0.87) if provider.lower().strip() in {"deepseek-v4-pro", "deepseek-reasoner"} else (0.003625, 0.28)
    return input_tokens * in_rate / 1_000_000 + output_tokens * out_rate / 1_000_000


def group_pages_for_batching(
    pages: List[List[OCRSegment]], max_pages: int = 5, max_segments: int = 80, max_chars: int = 120000,
) -> List[List[List[OCRSegment]]]:
    batches: List[List[List[OCRSegment]]] = []
    current: List[List[OCRSegment]] = []
    segment_count = character_count = 0
    for page in pages:
        page_segments = len(page)
        page_chars = sum(len(segment.source_text) for segment in page)
        if current and (len(current) >= max_pages or segment_count + page_segments > max_segments or character_count + page_chars > max_chars):
            batches.append(current)
            current, segment_count, character_count = [], 0, 0
        current.append(page)
        segment_count += page_segments
        character_count += page_chars
    if current:
        batches.append(current)
    return batches


class DeepSeekBatchTranslator:
    """Provider-local batching; shared Groq translation behavior remains unchanged."""

    def __init__(self, client: Any, provider: str = "deepseek-v4-flash"):
        self.client = client
        self.provider = provider

    async def translate_page_batch(
        self, pages: List[List[OCRSegment]], glossary: Tuple[Dict[str, Any], ...] = (),
        context: Tuple[Dict[str, Any], ...] = (), genre: str = "modern_cultivation",
    ) -> BatchTranslationResult:
        segments = [segment for page in pages for segment in page]
        expected_ids = tuple(segment.segment_id for segment in segments)
        if not expected_ids:
            return BatchTranslationResult({}, getattr(self.client, "model", "deepseek-chat"), 1, 0, 0, 0.0)

        body = {
            "task": "Translate ordered segments as one continuous Thai manga scene. Return JSON only.",
            "response_schema": {"translations": [{"id": "string", "th": "string"}]},
            "genre": genre,
            "segments": [{
                "segment_id": segment.segment_id,
                "page_index": segment.page_index,
                "reading_order": segment.reading_order,
                "text": segment.source_text,
            } for segment in segments],
            "glossary": [dict(item) for item in glossary],
            "context": [dict(item) for item in context[-8:]],
        }
        result = await self.client.generate_chat_completion_result(
            messages=[
                {"role": "system", "content": VETERAN_TRANSLATOR_SYSTEM_PROMPT + "\nReturn JSON only; preserve every source clause, glossary term, and identity."},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ],
            temperature=0.15,
            max_tokens=3000,
        )
        try:
            translations = parse_translation_response(result.text, expected_ids, allow_partial=False)
            if not translations:
                raise RuntimeError("DeepSeek batch result is incomplete")
        except TranslationResponseError as error:
            raise RuntimeError("DeepSeek batch result is incomplete") from error
        return BatchTranslationResult(
            translations=translations,
            model=result.model,
            attempts=result.attempts,
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            cost_usd=calculate_deepseek_cost_usd(self.provider, result.prompt_tokens, result.completion_tokens),
        )
