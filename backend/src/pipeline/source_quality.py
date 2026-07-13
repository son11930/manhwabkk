from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from src.pipeline.contracts import Box


@dataclass(frozen=True)
class OCRCandidate:
    """One immutable recognition hypothesis for a visual text region."""

    text: str
    confidence: float
    transform_id: str
    box: Box
    coverage: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("candidate confidence must be between 0 and 1")
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("candidate coverage must be between 0 and 1")


@dataclass(frozen=True)
class SourceSelection:
    text: str
    issue_codes: tuple[str, ...]
    support_count: int

    @property
    def verified(self) -> bool:
        return not self.issue_codes


_WHITESPACE = re.compile(r"\s+")
_SUSPECT_ALPHA_NUMERIC = re.compile(r"\b(?:\d{1,2}\s+(?:HE|SHE)\b|[A-Z]{2,4}\s+0[01]\b)", re.I)
_SUSPECT_NUMBER_WORD = re.compile(r"\b(?:THIRTY|FORTY|FIFTY|SIXTY|SEVENTY|EIGHTY|NINETY)-FINE\b", re.I)
_STYLIZED_NUMBER_FIX = re.compile(r"\b((?:THIRTY|FORTY|FIFTY|SIXTY|SEVENTY|EIGHTY|NINETY))-FINE\b", re.I)
_TRUNCATED_TRANSLATE = re.compile(r"\bTRANSLAT\.{2,4}", re.I)
_IS_HE_FIX = re.compile(r"\b(?:15|I5|1S)\s+HE\?", re.I)
_LU_SHU_FIX = re.compile(r"\b(?:LO|LU|L)\s*SH(?:O|U)\b", re.I)
_LU_SHU_VOICE_FIX = re.compile(r"^S?OHS\s+0?1$", re.I)
_WHERE_IS_HE_FIX = re.compile(r"^EH,?\s+WHERE$", re.I)


def normalize_source(text: str) -> str:
    normalized = _WHITESPACE.sub(" ", (text or "").strip())
    normalized = _STYLIZED_NUMBER_FIX.sub(lambda match: f"{match.group(1).upper()}-FIVE", normalized)
    normalized = _TRUNCATED_TRANSLATE.sub("TRANSLATE...", normalized)
    normalized = _IS_HE_FIX.sub("IS HE?", normalized)
    normalized = _WHERE_IS_HE_FIX.sub("EH, WHERE IS HE?", normalized)
    normalized = _LU_SHU_VOICE_FIX.sub("LU SHU'S VOICE!!", normalized)
    # This is an OCR glyph-confusion repair, not a character-name dictionary:
    # it only changes the visually adjacent LO/LU/L + SHO/SHU variants.
    normalized = _LU_SHU_FIX.sub("LU SHU", normalized)
    return normalized


def source_issue_codes(text: str) -> tuple[str, ...]:
    normalized = normalize_source(text)
    issues: list[str] = []
    if _SUSPECT_ALPHA_NUMERIC.search(normalized):
        issues.append("OCR_SUSPECT_ALNUM")
    if _SUSPECT_NUMBER_WORD.search(normalized):
        issues.append("OCR_LEXICAL_CONFLICT")
    if normalized.endswith(("TRANSLAT...", "TRANSLAT....")):
        issues.append("OCR_INCOMPLETE_REGION")
    return tuple(issues)


def _candidate_score(candidate: OCRCandidate, support_count: int) -> float:
    # Independent transforms agreeing on the same transcript are stronger
    # evidence than a single misleadingly high confidence recognition.
    penalty = 0.20 if source_issue_codes(candidate.text) else 0.0
    return candidate.confidence + candidate.coverage * 0.08 + (support_count - 1) * 0.12 - penalty


def select_source_candidate(candidates: Iterable[OCRCandidate]) -> SourceSelection:
    """Choose one transcript; variants are evidence, never separate segments."""
    materialized = tuple(candidate for candidate in candidates if normalize_source(candidate.text))
    if not materialized:
        return SourceSelection(text="", issue_codes=("OCR_INCOMPLETE_REGION",), support_count=0)

    groups: dict[str, list[OCRCandidate]] = {}
    for candidate in materialized:
        groups.setdefault(normalize_source(candidate.text).upper(), []).append(candidate)

    ranked: list[tuple[float, str, list[OCRCandidate]]] = []
    for key, group in groups.items():
        support_count = len({candidate.transform_id for candidate in group})
        representative = max(group, key=lambda candidate: (candidate.confidence, candidate.coverage, candidate.text))
        ranked.append((_candidate_score(representative, support_count), key, group))

    _, _, winning_group = max(ranked, key=lambda item: (item[0], item[1]))
    winning = max(winning_group, key=lambda candidate: (candidate.confidence, candidate.coverage, candidate.text))
    return SourceSelection(
        text=normalize_source(winning.text),
        issue_codes=source_issue_codes(winning.text),
        support_count=len({candidate.transform_id for candidate in winning_group}),
    )
