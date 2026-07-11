from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


Box = Tuple[int, int, int, int]


@dataclass(frozen=True)
class OCRSegment:
    """Immutable OCR evidence for one ordered speech segment."""

    segment_id: str
    page_index: int
    reading_order: int
    box: Box
    raw_lines: Tuple[str, ...]
    source_text: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("segment_id is required")
        if self.page_index < 0 or self.reading_order < 1:
            raise ValueError("page_index and reading_order must be positive")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if len(self.box) != 4:
            raise ValueError("box must contain four coordinates")


@dataclass(frozen=True)
class TranslationBatchRequest:
    """Chapter-aware request with a bounded rolling context window."""

    segments: Tuple[OCRSegment, ...]
    profile: Mapping[str, Any]
    glossary: Tuple[Mapping[str, Any], ...] = ()
    context: Tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if len(self.context) > 8:
            raise ValueError("rolling context is limited to eight segments")
        segment_ids = tuple(segment.segment_id for segment in self.segments)
        if len(set(segment_ids)) != len(segment_ids):
            raise ValueError("segment IDs must be unique")


@dataclass(frozen=True)
class TranslationResult:
    """Auditable translation result retained from draft through QC."""

    segment_id: str
    source_text: str
    draft_thai: str
    final_thai: str
    model: str
    attempts: int
    qc_status: str
    issue_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least one")
        if self.qc_status not in {"PENDING", "APPROVED", "NEEDS_REVIEW"}:
            raise ValueError("invalid QC status")
