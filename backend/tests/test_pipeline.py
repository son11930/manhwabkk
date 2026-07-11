import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from PIL import Image
import io
from src.domains.jobs.repository import JobRepository
from src.domains.manga.repository import SeriesRepository, ChapterRepository, PageRepository

@pytest.mark.asyncio
async def test_scraper_extracts_images_and_links():
    """Test extracting manga image URLs and dynamic navigation links from HTML."""
    from src.infrastructure.scraper.scraper_service import ScraperService
    
    sample_html = """
    <html>
        <body>
            <div class="chapter-content">
                <img class="page-img" src="https://cdn.example.com/ch1/p1.jpg" />
                <img class="page-img" src="https://cdn.example.com/ch1/p2.jpg" />
            </div>
            <div class="navigation">
                <a class="prev-btn" href="https://example.com/manga/solo/ch-0">Prev Chapter</a>
                <a class="next-btn" href="https://example.com/manga/solo/ch-2">Next Chapter</a>
            </div>
        </body>
    </html>
    """
    scraper = ScraperService()
    result = scraper.parse_chapter_page(sample_html, base_url="https://example.com")
    
    assert len(result["image_urls"]) == 2
    assert result["image_urls"][0] == "https://cdn.example.com/ch1/p1.jpg"
    assert result["next_chapter_url"] == "https://example.com/manga/solo/ch-2"
    assert result["prev_chapter_url"] == "https://example.com/manga/solo/ch-0"

@pytest.mark.asyncio
async def test_ai_translator_groq_prompt():
    """Test Groq API translator prompt formatting and response extraction."""
    from src.pipeline.translator import AITranslatorEngine
    
    translator = AITranslatorEngine()
    
    # Mock HTTPX response from Groq API (using MagicMock for synchronous .json())
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "คุณได้รับสิทธิ์ในการเป็นผู้เล่น!"
                    }
                }
            ]
        }
        mock_post.return_value = mock_response
        
        translated = await translator.translate_text("You have acquired the right to become a Player!")
        assert "ผู้เล่น" in translated
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert "gsk_" in str(call_kwargs.get("headers", {})) or "Bearer " in str(call_kwargs.get("headers", {}))

def test_typesetter_draws_thai_text():
    """Test drawing word-wrapped Thai text onto image coordinates using Pillow."""
    from src.pipeline.typesetter import TypesetterEngine
    
    img = Image.new("RGB", (300, 300), color=(255, 255, 255))
    typesetter = TypesetterEngine()
    
    # Draw text in speech box (50, 50, 250, 150)
    box = (50, 50, 250, 150)
    result_img = typesetter.render_text_in_box(img, "ระบบแจ้งเตือน: เลเวลของคุณอัปเกรดเรียบร้อยแล้ว!", box)
    
    assert isinstance(result_img, Image.Image)
    # Verify that the image pixels inside the speech box changed from pure white
    left, top, right, bottom = box
    has_text_pixels = any(
        result_img.getpixel((x, y)) != (255, 255, 255)
        for x in range(left, right, 5)
        for y in range(top, bottom, 5)
    )
    assert has_text_pixels is True

@pytest.mark.asyncio
async def test_worker_full_translation_pipeline(test_session):
    """
    Test full worker orchestration:
    PENDING -> SCRAPING -> TRANSLATING -> COMPLETED
    Verifies database Series, Chapter, Page generation and R2 upload.
    """
    from src.pipeline.worker import TranslationPipelineWorker
    from src.infrastructure.storage.r2_service import R2StorageService
    
    job_repo = JobRepository(test_session)
    job = await job_repo.create({
        "source_url": "https://example.com/manga/solo-leveling/chapter-1",
        "status": "PENDING",
        "progress_percent": 0
    })
    
    # Mock scraper service to return dummy image bytes
    fake_img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    img_byte_arr = io.BytesIO()
    fake_img.save(img_byte_arr, format="JPEG")
    fake_img_bytes = img_byte_arr.getvalue()
    
    mock_scraper = AsyncMock()
    mock_scraper.fetch_chapter_data.return_value = {
        "series_slug": "solo-leveling",
        "series_title": "Solo Leveling",
        "chapter_number": "chapter-1",
        "next_chapter_url": "https://example.com/manga/solo-leveling/chapter-2",
        "prev_chapter_url": None,
        "pages": [
            {"index": 1, "image_bytes": fake_img_bytes, "raw_url": "http://example.com/p1.jpg"}
        ]
    }
    
    mock_ocr = AsyncMock()
    mock_ocr.detect_and_extract.return_value = [
        {"box": (10, 10, 80, 40), "text": "Arise!"}
    ]
    
    mock_translator = AsyncMock()
    mock_translator.translate_text.return_value = "จงตื่นขึ้น!"
    mock_translator._is_valid_thai_translation = MagicMock(return_value=True)
    
    mock_r2 = AsyncMock(spec=R2StorageService)
    mock_r2.upload_image.return_value = "https://pub-test.r2.dev/solo-leveling/chapter-1/1.jpg"
    
    worker = TranslationPipelineWorker(
        session=test_session,
        scraper=mock_scraper,
        ocr=mock_ocr,
        translator=mock_translator,
        r2_service=mock_r2
    )
    
    # Run pipeline
    completed_job = await worker.process_job(job.id)
    
    assert completed_job.status == "COMPLETED"
    assert completed_job.progress_percent == 100
    
    # Verify R2 upload called with immutable cache
    mock_r2.upload_image.assert_called_once()
    
    # Verify DB records created
    series_repo = SeriesRepository(test_session)
    series = await series_repo.find_by_slug("solo-leveling", include_chapters=True)
    assert series is not None
    assert len(series.chapters) == 1
    assert series.chapters[0].chapter_number == "chapter-1"
    
    chapter_repo = ChapterRepository(test_session)
    chapter = await chapter_repo.find_by_series_and_number(series.id, "chapter-1", include_pages=True)
    assert chapter is not None
    assert len(chapter.pages) == 1
    assert chapter.pages[0].image_url.startswith("https://pub-test.r2.dev/solo-leveling/chapter-1/1.jpg")

def test_translator_dynamic_genre_contextualizer():
    """Verify that get_genre_context_instructions returns correct pronoun and stylistic instructions for manga genres."""
    from src.pipeline.translator import get_genre_context_instructions
    wuxia_instructions = get_genre_context_instructions("wuxia")
    assert "ข้า" in wuxia_instructions and "เจ้า" in wuxia_instructions and "อาวุโส" in wuxia_instructions
    
    action_instructions = get_genre_context_instructions("modern_action")
    assert "แก" in action_instructions or "นาย" in action_instructions
    assert "แรงก์ S" in action_instructions

def test_translator_veteran_prompt_examples():
    """Verify that AITranslatorEngine uses Veteran Scanlator persona and contains contrastive human scanlation examples."""
    from src.pipeline.translator import AITranslatorEngine
    translator = AITranslatorEngine()
    assert "Veteran Scanlator" in translator.system_prompt or "นักแปลมังฮวา" in translator.system_prompt
    assert "ก็แกรั้นจะให้ฉันทำเองนี่นา" in translator.system_prompt
    assert "โชว์โง่" in translator.system_prompt
