"""Unit tests for Group 1 Credit / Watermark / License Plate pre-translation filter."""

import pytest
from src.pipeline.ocr import MangaOCREngine


def test_credit_watermark_filter_identifies_watermarks_and_credits():
    """Watermarks, scanlation recruitment credits, and license plates must be filtered."""
    watermarks = [
        "本章节仅限腾讯动漫手机APP观看",
        "MASK3钻头",
        "有朋 自远方来， 还不 赶快 加群 COME ON!! 道元新生群： 811751222 群： 921V6969E",
        "皖A·77E·A",
    ]
    for text in watermarks:
        assert MangaOCREngine.is_noise_credit_or_watermark(text) is True, f"Failed to detect watermark: {text}"


def test_credit_watermark_filter_preserves_narrative_dialogue():
    """Real dialogue and narrative lines must never be filtered out."""
    dialogues = [
        "LU SHU'S VOICE!!",
        "LU SHU, PLEASE HELP ME TRANSLATE...",
        "EH, WHERE IS HE?",
        "DON'T! IS THIRTY-FIVE OKAY? TAKE EVERYTHING WITH THIRTY-FIVE STONES!",
        "HEAVENLY KING LI, HOW COME THERE ARE SO MANY F-LEVEL AND D-LEVEL PEOPLE?",
    ]
    for text in dialogues:
        assert MangaOCREngine.is_noise_credit_or_watermark(text) is False, f"False positive on dialogue: {text}"
