from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import httpx

class ScraperService:
    """
    Scraper service for extracting manga images and navigation links from English webtoons.
    """
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def parse_chapter_page(self, html_content: str, base_url: str) -> Dict[str, Any]:
        """
        Parses HTML content to extract manga page image URLs and dynamic 'Next Chapter' / 'Prev Chapter' links.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 1. Extract Images (look for img tags with common page/reader classes or inside reader div)
        image_urls = []
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            src = src.strip()
            # Filter out tiny icons or logos if possible, check common image extensions or reader structure
            if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]) or "page-img" in img.get("class", []):
                full_url = urljoin(base_url, src)
                if full_url not in image_urls:
                    image_urls.append(full_url)
                    
        # 2. Extract Navigation Links
        next_url = None
        prev_url = None
        
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True).lower()
            classes = " ".join(a_tag.get("class", [])).lower()
            href = urljoin(base_url, a_tag["href"].strip())
            
            if "next" in text or "next" in classes:
                next_url = href
            elif "prev" in text or "prev" in classes:
                prev_url = href
                
        return {
            "image_urls": image_urls,
            "next_chapter_url": next_url,
            "prev_chapter_url": prev_url
        }

    async def fetch_chapter_data(self, source_url: str) -> Dict[str, Any]:
        """
        Fetches HTML from source URL, downloads image bytes, and prepares structured chapter payload.
        """
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            
            parsed = self.parse_chapter_page(resp.text, base_url=source_url)
            
            # Derive basic series slug and chapter number from URL string
            parts = [p for p in source_url.rstrip("/").split("/") if p]
            chapter_number = parts[-1] if parts else "chapter-1"
            series_slug = parts[-2] if len(parts) >= 2 else "unknown-series"
            series_title = series_slug.replace("-", " ").title()
            
            pages = []
            for idx, img_url in enumerate(parsed["image_urls"], start=1):
                try:
                    img_resp = await client.get(img_url)
                    if img_resp.status_code == 200:
                        pages.append({
                            "index": idx,
                            "image_bytes": img_resp.content,
                            "raw_url": img_url
                        })
                except Exception:
                    continue
                    
            return {
                "series_slug": series_slug,
                "series_title": series_title,
                "chapter_number": chapter_number,
                "next_chapter_url": parsed["next_chapter_url"],
                "prev_chapter_url": parsed["prev_chapter_url"],
                "pages": pages
            }
