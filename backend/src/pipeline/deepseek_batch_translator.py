import json
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from src.pipeline.contracts import OCRSegment
from src.pipeline.translator import (
    parse_translation_response,
    TranslationResponseError,
    VETERAN_TRANSLATOR_SYSTEM_PROMPT,
)


@dataclass(frozen=True)
class BatchTranslationResult:
    translations: Dict[str, str]
    model: str
    attempts: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def calculate_deepseek_cost_usd(provider: str, input_tokens: int, output_tokens: int) -> float:
    provider_lower = (provider or "").lower().strip()
    if provider_lower in ("deepseek-v4-pro", "deepseek-reasoner"):
        in_rate = 0.55 / 1_000_000.0
        out_rate = 2.19 / 1_000_000.0
    elif provider_lower == "deepseek-v4-flash":
        in_rate = 0.28 / 1_000_000.0
        out_rate = 0.56 / 1_000_000.0
    else:
        # deepseek-chat default
        in_rate = 0.14 / 1_000_000.0
        out_rate = 0.28 / 1_000_000.0

    return (input_tokens * in_rate) + (output_tokens * out_rate)


def group_pages_for_batching(
    pages: List[List[OCRSegment]],
    max_pages: int = 5,
    max_segments: int = 80,
    max_chars: int = 120000,
) -> List[List[List[OCRSegment]]]:
    """
    Group consecutive manga pages into batches up to `max_pages` per batch,
    ensuring that total segments and input characters do not exceed safety thresholds.
    """
    batches: List[List[List[OCRSegment]]] = []
    current_batch: List[List[OCRSegment]] = []
    current_segments = 0
    current_chars = 0

    for page_segs in pages:
        page_seg_count = len(page_segs)
        page_char_count = sum(len(s.source_text) for s in page_segs)

        # Check if adding this page exceeds limits
        if current_batch and (
            len(current_batch) >= max_pages
            or current_segments + page_seg_count > max_segments
            or current_chars + page_char_count > max_chars
        ):
            batches.append(current_batch)
            current_batch = []
            current_segments = 0
            current_chars = 0

        current_batch.append(page_segs)
        current_segments += page_seg_count
        current_chars += page_char_count

    if current_batch:
        batches.append(current_batch)

    return batches


class DeepSeekBatchTranslator:
    """
    Translates up to 5 consecutive manga pages simultaneously using DeepSeek V4.
    """

    def __init__(self, client: Any, provider: str = "deepseek-v4-flash"):
        self.client = client
        self.provider = provider

    async def translate_page_batch(
        self,
        pages: List[List[OCRSegment]],
        glossary: Tuple[Dict[str, Any], ...] = (),
        context: Tuple[Dict[str, Any], ...] = (),
        genre: str = "modern_cultivation",
    ) -> BatchTranslationResult:
        all_segments: List[OCRSegment] = []
        for p in pages:
            all_segments.extend(p)

        expected_ids = tuple(s.segment_id for s in all_segments)
        if not expected_ids:
            return BatchTranslationResult(
                translations={},
                model=getattr(self.client, "model", "deepseek-chat"),
                attempts=1,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
            )

        page_sections: List[str] = []
        for page_idx, page_segs in enumerate(pages, start=1):
            seg_items = [
                {"segment_id": seg.segment_id, "text": seg.source_text}
                for seg in page_segs
            ]
            page_sections.append(f"=== หน้า {page_idx} ===\n" + json.dumps(seg_items, ensure_ascii=False))

        body_content = (
            f"Genre: {genre}\n"
            f"Translate all segments across the {len(pages)} pages below into natural Thai manga dialogue.\n\n"
            + "\n\n".join(page_sections)
        )

        messages = [
            {"role": "system", "content": VETERAN_TRANSLATOR_SYSTEM_PROMPT},
            {"role": "user", "content": body_content},
        ]

        result = await self.client.generate_chat_completion_result(
            messages=messages,
            temperature=0.15,
            max_tokens=3000,
        )

        try:
            translations = parse_translation_response(result.text, expected_ids, allow_partial=False)
        except TranslationResponseError:
            # Fallback allow_partial if full JSON had minor syntax errors
            translations = parse_translation_response(result.text, expected_ids, allow_partial=True)

        # Fill any missing/refused segments with source text
        for seg in all_segments:
            if seg.segment_id not in translations or not translations[seg.segment_id].strip():
                translations[seg.segment_id] = seg.source_text

        cost = calculate_deepseek_cost_usd(
            self.provider,
            result.prompt_tokens,
            result.completion_tokens,
        )

        return BatchTranslationResult(
            translations=translations,
            model=result.model,
            attempts=result.attempts,
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            cost_usd=cost,
        )
