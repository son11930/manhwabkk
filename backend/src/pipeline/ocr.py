from typing import List, Dict, Any, Tuple
from PIL import Image
import io

class MangaOCREngine:
    """
    OCR Engine for detecting speech bubbles and extracting English text.
    In production, integrates with MangaOCR / EasyOCR / PaddleOCR models.
    """
    def __init__(self):
        pass

    async def detect_and_extract(self, image_bytes: bytes) -> List[Dict[str, Any]]:
        """
        Analyzes image bytes and returns speech bubble bounding boxes with detected text.
        Format: [{'box': (left, top, right, bottom), 'text': 'extracted text'}]
        """
        # In actual execution, passes image to OCR model.
        # Here we provide standard bounding box format required by pipeline.
        return []
