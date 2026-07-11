import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock
from PIL import Image
import asyncio

from src.infrastructure.ai.groq_client import GroqClient, _exhausted_models
from src.pipeline.inpainter import InpainterEngine
from src.pipeline.translator import AITranslatorEngine

@pytest.mark.asyncio
async def test_groq_client_circuit_breaker_skips_exhausted_model():
    """Test that models in _exhausted_models are skipped immediately without making HTTP requests."""
    client = GroqClient(model="test-primary-model")
    
    # Put test-primary-model in cooldown
    _exhausted_models["test-primary-model"] = time.time() + 1800.0
    
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Translated text from backup AI"}}]
        }
        mock_post.return_value = mock_response
        
        result = await client.generate_chat_completion(messages=[{"role": "user", "content": "hello"}])
        assert result == "Translated text from backup AI"
        
        # Verify that post was called, but NOT for test-primary-model
        assert mock_post.called
        called_model = mock_post.call_args.kwargs["json"]["model"]
        assert called_model != "test-primary-model"
        assert called_model == "openai/gpt-oss-120b"  # First backup model with independent quota
        
    # Clean up registry
    _exhausted_models.clear()

@pytest.mark.asyncio
async def test_groq_client_records_429_in_circuit_breaker():
    """Test that receiving HTTP 429 adds the model to _exhausted_models."""
    client = GroqClient(model="test-exhausted-model")
    _exhausted_models.clear()
    
    with patch("httpx.AsyncClient.post") as mock_post:
        # First call returns 429, second (backup) returns 200
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        mock_resp_429.headers = {"Retry-After": "60.0"}
        
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {
            "choices": [{"message": {"content": "Success from backup"}}]
        }
        
        mock_post.side_effect = [mock_resp_429, mock_resp_200]
        
        result = await client.generate_chat_completion(messages=[{"role": "user", "content": "hi"}])
        assert result == "Success from backup"
        assert "test-exhausted-model" in _exhausted_models
        assert _exhausted_models["test-exhausted-model"] > time.time()
        
    _exhausted_models.clear()

def test_inpainter_luminance_check_prevents_black_box():
    """Test that sampling dark pixels (L < 180) defaults to pure white (255, 255, 255)."""
    from src.pipeline.inpainter import InpainterEngine
    inpainter = InpainterEngine()
    
    # 1. Create image with dark text/border (RGB 10, 10, 10, L=10 < 180)
    dark_img = Image.new("RGB", (100, 100), color=(10, 10, 10))
    box = (10, 10, 80, 80)
    
    cleaned_dark = inpainter.clean_speech_box(dark_img, box)
    
    # Check center of speech box - should be pure white (255, 255, 255) instead of sampled (10, 10, 10)
    center_pixel_dark = cleaned_dark.getpixel((45, 45))
    assert center_pixel_dark == (255, 255, 255), f"Expected (255, 255, 255) but got {center_pixel_dark}"
    
    # 2. Create image with colorful special status box (RGB 250, 220, 50, high saturation diff >= 60)
    color_img = Image.new("RGB", (100, 100), color=(250, 220, 50))
    cleaned_color = inpainter.clean_speech_box(color_img, box)
    
    center_pixel_color = cleaned_color.getpixel((45, 45))
    assert center_pixel_color == (250, 220, 50), f"Expected (250, 220, 50) but got {center_pixel_color}"

def test_translator_concise_prompts():
    """Verify that translate_batch structures clean index prompts without formatting boilerplate."""
    translator = AITranslatorEngine()
    
    # Test internal helper formatting if accessible or mock _generate_completion
    with patch.object(translator.client, "generate_chat_completion", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "[1] สวัสดี\n[2] ลาก่อน"
        
        # We run the batch
        import asyncio
        res = asyncio.run(translator.translate_batch(["Hello", "Goodbye"]))
        
        assert res == ["สวัสดี", "ลาก่อน"]
        mock_gen.assert_called_once()
        
        # Check what was sent to LLM
        call_args = mock_gen.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        user_msg = messages[1]["content"]
        
        assert "[1] Hello" in user_msg and "[2] Goodbye" in user_msg
        assert len(user_msg) < 650, "User prompt in batch should be concise without heavy boilerplate"

@pytest.mark.asyncio
async def test_groq_client_verified_hierarchy():
    """Verify GroqClient uses Semaphore(3) and the verified 8-model hierarchy ordered by intelligence and TPM."""
    from src.infrastructure.ai.groq_client import GroqClient, _groq_semaphore
    assert _groq_semaphore._value == 3, "Global semaphore should allow 3 concurrent requests"
    
    client = GroqClient(model="llama-3.3-70b-versatile")
    expected_hierarchy = [
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "qwen/qwen3-32b",
        "qwen/qwen3.6-27b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-20b",
        "allam-2-7b",
        "groq/compound",
        "groq/compound-mini"
    ]
    assert client.get_fallback_models() == expected_hierarchy

@pytest.mark.asyncio
async def test_translator_no_meta_language_and_spacing():
    """Verify heuristic clause spacing and removal of negative constraints from system prompt."""
    translator = AITranslatorEngine()
    
    # Check prompt has natural scanlator examples instead of negative rules that trigger echoing
    assert "❌ AI ทื่อ:" in translator.system_prompt and "✅ คนแปลอาชีพ:" in translator.system_prompt
    assert "[ห้ามทับศัพท์ภาษาอังกฤษทั่วไป]" not in translator.system_prompt
    
    # Test heuristic clause separator on unspaced Thai sentence
    unspaced = "ข้าจะไปเก็บเกี่ยวผลผลิตบ้างการรอคอยที่ซากจะเปิดนั้นน่าเบื่อ"
    spaced = translator._post_process_spacing(unspaced)
    assert " การรอคอย" in spaced, f"Expected space before 'การรอคอย', got '{spaced}'"

@pytest.mark.asyncio
async def test_translator_valid_thai_check_and_retry():
    """Verify _is_valid_thai_translation correctly identifies English or empty strings and triggers single box retry."""
    translator = AITranslatorEngine()
    
    assert translator._is_valid_thai_translation("สวัสดีชาวโลก") is True
    assert translator._is_valid_thai_translation("THE ORDER OF PHOENIX") is False
    assert translator._is_valid_thai_translation("") is False
    assert translator._is_valid_thai_translation("   ") is False
    
    # Verify translate_batch triggers single retry if a box returns non-Thai
    with patch.object(translator.client, "generate_chat_completion", new_callable=AsyncMock) as mock_gen:
        # First call returns English for box 2, second call (retry) returns Thai
        mock_gen.side_effect = [
            "[1] สวัสดี\n[2] POWERHOUSE",
            "ขุมพลังอันยิ่งใหญ่"
        ]
        res = await translator.translate_batch(["Hello", "POWERHOUSE"])
        assert res == ["สวัสดี", "ขุมพลังอันยิ่งใหญ่"]
        assert mock_gen.call_count == 2

@pytest.mark.asyncio
async def test_translator_eliminates_ai_meta_language_from_screenshot():
    """Verify that verbose AI meta-language and prompt echoes (like in chapter 153 screenshot) are stripped and rejected."""
    translator = AITranslatorEngine()
    
    screenshot_garbage = (
        "but the actual input is Chinese...\n"
        "I need to handle this...\n"
        "In Chinese usually means to undertake manufacturing/production\n"
        "Give me context tags\n"
        "แอคชั่น ฮันเตอร์ ดันเจี้ยน เกิดใหม่ในโลกเกม\n"
        "s likely a system prompt or a button like 'Accept' 'Confirm'"
    )
    
    cleaned = translator._post_process_spacing(screenshot_garbage)
    assert cleaned == "", f"Expected empty cleaned string, got '{cleaned}'"
    assert translator._is_valid_thai_translation(screenshot_garbage) is False
    assert translator._is_valid_thai_translation("บริบทเฉพาะเรื่อง: แอคชั่นสมัยใหม่ / ฮันเตอร์") is False

@pytest.mark.asyncio
async def test_translator_batch_chunking_prevents_413():
    """Verify that translate_batch chunks inputs larger than 8 boxes to prevent HTTP 413 Payload Too Large."""
    translator = AITranslatorEngine()
    texts = [f"Text {i}" for i in range(18)]
    with patch.object(translator.client, "generate_chat_completion", new_callable=AsyncMock) as mock_gen:
        # 18 items -> chunks of 8, 8, 2 -> 3 batch calls
        mock_gen.side_effect = [
            "\n".join([f"[{i+1}] ไทย {i}" for i in range(8)]),
            "\n".join([f"[{i+1}] ไทย {i+8}" for i in range(8)]),
            "\n".join([f"[{i+1}] ไทย {i+16}" for i in range(2)])
        ]
        res = await translator.translate_batch(texts)
        assert len(res) == 18
        assert mock_gen.call_count == 3
        assert res[0] == "ไทย 0"
        assert res[17] == "ไทย 17"

def test_translator_conversational_spacing_and_echoes():
    """Verify that conversational connectors get spacing and screenshot 4/5 echoes are rejected."""
    translator = AITranslatorEngine()
    # Check spacing insertion before conversational clause connectors and after tail words
    raw_unspaced = "นางสาวนี่ไม่ธรรมดาเลยสักนิดคิดว่านางเป็นแค่เด็กสาวธรรมดาๆเหรอไม่บางไม่ธรรมดาแน่นอน"
    spaced = translator._post_process_spacing(raw_unspaced)
    assert "เหรอ ไม่บาง" in spaced or "สักนิด คิดว่า" in spaced or "เลย สักนิด" in spaced
    
    # Check rejection of screenshot 4 & 5 prompt echoes
    echo_1 = "PronounsRecommended: ฉัน,นาย,แก,พวกเรา,ท่านกิลด์มาสเตอร์"
    echo_2 = "QC/N: CULTIVATOMON"
    echo_3 = "Let'sconstruct'คำอารมณ์ลดลงจากXXX'-Applyspacingrule"
    assert translator._is_valid_thai_translation(echo_1) is False
    assert translator._is_valid_thai_translation(echo_2) is False
    assert translator._is_valid_thai_translation(echo_3) is False
