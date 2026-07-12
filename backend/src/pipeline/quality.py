from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence

from src.pipeline.contracts import OCRSegment


@dataclass(frozen=True)
class QualityAssessment:
    passed: bool
    issue_codes: tuple[str, ...]
    requires_semantic_review: bool


class TranslationQualityGate:
    """Cheap, deterministic fidelity checks applied before selective LLM review."""

    _META_MARKERS = (
        "here is the translation",
        "translation:",
        "explanation:",
        "system prompt",
        "คำแปล:",
        "คำอธิบาย:",
        "กฎเหล็ก",
    )
    _SOURCE_NEGATION = re.compile(r"\b(?:not|never|no|cannot|can't|won't|don't|doesn't|didn't)\b", re.I)
    _THAI_NEGATION = ("ไม่", "มิ", "ห้าม", "อย่า", "ไม่ได้", "ไม่มี")
    _PAST_MARKERS = re.compile(r"\b(?:before|previously|in the past|used to|back then)\b", re.I)
    _NOW_MARKERS = re.compile(r"\b(?:now|currently|at present|these days)\b", re.I)
    _THAI_PAST = ("เมื่อก่อน", "ในอดีต", "แต่ก่อน", "ก่อนหน้านี้", "สมัยก่อน")
    _THAI_NOW = ("ตอนนี้", "ปัจจุบัน", "เดี๋ยวนี้", "ตอนปัจจุบัน")
    _SEMANTIC_RISK = re.compile(
        r"\b(?:but|however|although|though|either|or|because|therefore|so|should|"
        r"before|past|now|never|not|unless|until|after|while)\b",
        re.I,
    )
    _SWEET_POINTS = re.compile(r"\bsweet\s+points?\b", re.I)

    def evaluate(
        self,
        segment: OCRSegment,
        thai_text: str,
        glossary: Sequence[Mapping[str, object]],
    ) -> QualityAssessment:
        source = segment.source_text.strip()
        target = (thai_text or "").strip()
        issues: list[str] = []

        if not target:
            issues.append("EMPTY_TRANSLATION")

        lower_target = target.lower()
        if any(marker in lower_target for marker in self._META_MARKERS):
            issues.append("META_TEXT")

        source_numbers = re.findall(r"\d+(?:\.\d+)?", source)
        target_numbers = re.findall(r"\d+(?:\.\d+)?", target)
        if source_numbers != target_numbers:
            issues.append("NUMBER_MISMATCH")

        rank_matches = re.findall(
            r"\b(?:rank|level|class|grade)\s*[-:]?\s*([A-FS]{1,3})\b|\b([A-FS]{1,3})\s*[-:]?\s*(?:rank|level|class|grade)\b|\b([A-FS]{1,3})-(?:rank|level|class|grade)\b",
            source,
            re.I,
        )
        source_ranks = [r.upper() for tup in rank_matches for r in tup if r]
        # Only match uppercase single letters B-F, S as ranks when rank keyword is present (exclude article 'a' / 'A')
        if re.search(r"\b(?:rank|level|class|grade)\b", source, re.I):
            for token in re.findall(r"\b([B-FS])\b", source):
                if token.isupper():
                    source_ranks.append(token.upper())
        if source_ranks:
            target_ranks = [value.upper() for value in re.findall(r"(?<![A-Za-z])([A-FS])(?![A-Za-z])", target, re.I)]
            thai_rank_map = {"A": "เอ", "B": "บี", "C": "ซี", "D": "ดี", "E": "อี", "F": "เอฟ", "S": "เอส"}
            if any(rank not in target_ranks and thai_rank_map.get(rank, "") not in target for rank in source_ranks):
                issues.append("RANK_MISMATCH")

        if self._SOURCE_NEGATION.search(source) and not any(token in target for token in self._THAI_NEGATION):
            issues.append("NEGATION_MISMATCH")

        has_past = bool(self._PAST_MARKERS.search(source))
        has_now = bool(self._NOW_MARKERS.search(source))
        if has_past and has_now:
            if not any(token in target for token in self._THAI_PAST) or not any(token in target for token in self._THAI_NOW):
                issues.append("TIMELINE_MISMATCH")

        if self._SWEET_POINTS.search(source):
            issues.append("AMBIGUOUS_TERM_REVIEW")

        for term in glossary:
            if str(term.get("gender", "")).lower() == "female":
                source_term = str(term.get("source", "")).strip()
                aliases = tuple(str(alias) for alias in term.get("aliases", ()) or ())
                if any(alias and alias.lower() in source.lower() for alias in (source_term, *aliases)):
                    if any(pronoun in target for pronoun in ("นาย", "เขา")):
                        issues.append("PRONOUN_GENDER_MISMATCH")
                        break
            if not bool(term.get("locked")):
                continue
            source_term = str(term.get("source", "")).strip()
            thai_term = str(term.get("thai", "")).strip()
            aliases = tuple(str(alias) for alias in term.get("aliases", ()) or ())
            candidates = (source_term, *aliases)
            if any(candidate and candidate.lower() in source.lower() for candidate in candidates):
                if thai_term and thai_term not in target:
                    issues.append("LOCKED_TERM_MISMATCH")
                    break

        ascii_words = re.findall(r"[A-Za-z]+", target)
        permitted_rank_letters = set(source_ranks) | {
            "A", "B", "C", "D", "E", "F", "S", "EX", "SS", "SSS",
            "RPG", "NPC", "CEO", "VIP", "STATUS", "LEVEL", "RANK", "MAX", "HP", "MP", "EXP"
        }
        if any(word.upper() not in permitted_rank_letters for word in ascii_words):
            issues.append("ENGLISH_LEAKAGE")

        source_letters = sum(character.isascii() and character.isalpha() for character in source)
        thai_chars = sum("\u0e00" <= character <= "\u0e7f" for character in target)
        length_ratio = thai_chars / max(source_letters, 1)
        if source_letters >= 20 and not 0.45 <= length_ratio <= 2.20:
            issues.append("LENGTH_RATIO_OUTLIER")

        word_count = len(re.findall(r"[A-Za-z0-9']+", source))
        requires_review = (
            word_count >= 14
            or bool(self._SEMANTIC_RISK.search(source))
            or bool(self._SWEET_POINTS.search(source))
        )
        unique_issues = tuple(dict.fromkeys(issues))
        return QualityAssessment(
            passed=not unique_issues,
            issue_codes=unique_issues,
            requires_semantic_review=requires_review,
        )

    def evaluate_batch(
        self,
        segments: Sequence[OCRSegment],
        translated_by_id: Mapping[str, str],
        glossary: Sequence[Mapping[str, object]],
    ) -> QualityAssessment:
        expected = {segment.segment_id for segment in segments}
        actual = set(translated_by_id)
        issues: list[str] = []
        requires_review = False
        if expected != actual:
            issues.append("RESULT_COUNT_MISMATCH")

        for segment in segments:
            assessment = self.evaluate(
                segment,
                translated_by_id.get(segment.segment_id, ""),
                glossary,
            )
            issues.extend(assessment.issue_codes)
            requires_review = requires_review or assessment.requires_semantic_review

        unique_issues = tuple(dict.fromkeys(issues))
        return QualityAssessment(
            passed=not unique_issues,
            issue_codes=unique_issues,
            requires_semantic_review=requires_review,
        )
