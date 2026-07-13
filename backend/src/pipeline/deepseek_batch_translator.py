import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.pipeline.contracts import OCRSegment
from src.pipeline.translator import VETERAN_TRANSLATOR_SYSTEM_PROMPT


@dataclass(frozen=True)
class BatchTranslationResult:
    translations: Dict[str, str]
    model: str
    attempts: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    parse_outcome: Optional["DeepSeekBatchParseOutcome"] = None


@dataclass(frozen=True)
class DeepSeekBatchParseOutcome:
    """Account for every expected segment without discarding a usable prefix."""

    translations: Dict[str, str]
    missing_ids: Tuple[str, ...]
    duplicate_ids: Tuple[str, ...]
    unknown_ids: Tuple[str, ...]
    parse_error: Optional[str] = None

    @property
    def outcome_type(self) -> str:
        if self.parse_error:
            return "INVALID_JSON"
        if not self.translations and len(self.missing_ids) > 0:
            return "EMPTY_CONTENT"
        if len(self.missing_ids) == 0:
            return "COMPLETE"
        return "PARTIAL"


def _response_entries(response_text: str) -> tuple[List[Any], Optional[str]]:
    """Return complete translation entries even when a response ends mid-JSON."""
    cleaned = re.sub(r"<think>.*?</think>", "", response_text or "", flags=re.DOTALL | re.IGNORECASE).strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = "\n".join(cleaned.splitlines()[1:-1]).strip()

    try:
        payload = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError) as error:
        marker = re.search(r'"translations"\s*:\s*\[', cleaned)
        if not marker:
            return [], str(error)

        decoder = json.JSONDecoder()
        entries: List[Any] = []
        index = marker.end()
        while index < len(cleaned):
            if cleaned[index] != "{":
                index += 1
                continue
            try:
                entry, end = decoder.raw_decode(cleaned, index)
            except json.JSONDecodeError:
                index += 1
                continue
            if isinstance(entry, dict):
                entries.append(entry)
            index = end
        return entries, str(error)

    entries = payload.get("translations") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return [], "translation response requires a translations list"
    return entries, None


def parse_deepseek_batch_response(
    response_text: str,
    expected_segment_ids: Tuple[str, ...],
) -> DeepSeekBatchParseOutcome:
    """Preserve only unambiguous expected IDs and account for contract violations.

    A repeated expected ID is deliberately withheld for recovery: accepting either
    occurrence would make the selected translation ambiguous.
    """
    entries, parse_error = _response_entries(response_text)
    expected = set(expected_segment_ids)
    candidate_texts: Dict[str, str] = {}
    seen_expected: set[str] = set()
    duplicates: List[str] = []
    unknown: List[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        segment_id = entry.get("segment_id", entry.get("id"))
        if not isinstance(segment_id, str) or not segment_id:
            continue
        if segment_id not in expected:
            if segment_id not in unknown:
                unknown.append(segment_id)
            continue
        if segment_id in seen_expected:
            if segment_id not in duplicates:
                duplicates.append(segment_id)
            continue

        seen_expected.add(segment_id)
        text = entry.get("text", entry.get("th", entry.get("target")))
        if isinstance(text, str) and text.strip():
            candidate_texts[segment_id] = text.strip()

    translations = {
        segment_id: candidate_texts[segment_id]
        for segment_id in expected_segment_ids
        if segment_id in candidate_texts and segment_id not in duplicates
    }
    missing_ids = tuple(segment_id for segment_id in expected_segment_ids if segment_id not in translations)
    return DeepSeekBatchParseOutcome(
        translations=translations,
        missing_ids=missing_ids,
        duplicate_ids=tuple(duplicates),
        unknown_ids=tuple(unknown),
        parse_error=parse_error,
    )


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


def append_batch_context(
    context: Tuple[Dict[str, str], ...],
    pages: List[List[OCRSegment]],
    translations: Mapping[str, str],
    *,
    max_items: int = 8,
) -> Tuple[Dict[str, str], ...]:
    """Commit a completed batch in reading order for the next DeepSeek call."""
    committed = [dict(item) for item in context]
    for page in pages:
        for segment in page:
            final_thai = translations.get(segment.segment_id, "").strip()
            if final_thai:
                committed.append({
                    "segment_id": segment.segment_id,
                    "source_text": segment.source_text,
                    "final_thai": final_thai,
                })
    return tuple(committed[-max_items:])


class DeepSeekBatchTranslator:
    """Provider-local batching; shared Groq translation behavior remains unchanged."""

    def __init__(self, client: Any, provider: str = "deepseek-v4-flash"):
        self.client = client
        self.provider = provider

    def _request_body(
        self,
        pages: List[List[OCRSegment]],
        glossary: Tuple[Dict[str, Any], ...],
        context: Tuple[Dict[str, Any], ...],
        genre: str,
    ) -> tuple[list[OCRSegment], dict[str, Any]]:
        segments = [segment for page in pages for segment in page]
        return segments, {
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

    def estimate_max_cost_usd(
        self, pages: List[List[OCRSegment]], glossary: Tuple[Dict[str, Any], ...] = (),
        context: Tuple[Dict[str, Any], ...] = (), genre: str = "modern_cultivation",
        max_output_tokens: int = 3000,
    ) -> float:
        """Conservative request ceiling using UTF-8 bytes as an input-token bound."""
        _, body = self._request_body(pages, glossary, context, genre)
        system_message = VETERAN_TRANSLATOR_SYSTEM_PROMPT + "\nReturn JSON only; preserve every source clause, glossary term, and identity."
        input_byte_bound = len(system_message.encode("utf-8")) + len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        return calculate_deepseek_cost_usd(self.provider, input_byte_bound, max_output_tokens)

    async def translate_page_batch(
        self, pages: List[List[OCRSegment]], glossary: Tuple[Dict[str, Any], ...] = (),
        context: Tuple[Dict[str, Any], ...] = (), genre: str = "modern_cultivation",
        max_output_tokens: int = 3000,
    ) -> BatchTranslationResult:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        segments, body = self._request_body(pages, glossary, context, genre)
        expected_ids = tuple(segment.segment_id for segment in segments)
        if not expected_ids:
            return BatchTranslationResult({}, getattr(self.client, "model", "deepseek-chat"), 1, 0, 0, 0.0)
        result = await self.client.generate_chat_completion_result(
            messages=[
                {"role": "system", "content": VETERAN_TRANSLATOR_SYSTEM_PROMPT + "\nReturn JSON only; preserve every source clause, glossary term, and identity."},
                {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
            ],
            temperature=0.15,
            max_tokens=max_output_tokens,
        )
        parse_outcome = parse_deepseek_batch_response(result.text, expected_ids)
        return BatchTranslationResult(
            translations=parse_outcome.translations,
            model=result.model,
            attempts=result.attempts,
            input_tokens=result.prompt_tokens,
            output_tokens=result.completion_tokens,
            cost_usd=calculate_deepseek_cost_usd(self.provider, result.prompt_tokens, result.completion_tokens),
            parse_outcome=parse_outcome,
        )
