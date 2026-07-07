from typing import List, Dict, Any, Tuple
from PIL import Image
import io

import numpy as np
import cv2

class MangaOCREngine:
    """
    OCR Engine for detecting speech bubbles and extracting English text.
    Uses RapidOCR (ONNX Runtime) for ultra-fast and accurate speech bubble detection.
    """
    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine = RapidOCR()
            self.is_ready = True
        except Exception:
            self.ocr_engine = None
            self.is_ready = False

    async def detect_and_extract(self, image_bytes: bytes) -> List[Dict[str, Any]]:
        """
        Analyzes image bytes and returns speech bubble bounding boxes with detected text.
        Format: [{'box': (left, top, right, bottom), 'text': 'extracted text'}]
        """
        if not self.is_ready or not image_bytes:
            return []

        try:
            # Convert image bytes to numpy BGR image for OpenCV/RapidOCR
            nparr = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                return []

            res, _ = self.ocr_engine(img_bgr)
            if not res or len(res) == 0:
                return []

            raw_boxes = []
            for item in res:
                poly = item[0]
                text = str(item[1]).strip()
                conf = float(item[2])
                if conf < 0.4 or not text or len(text) < 2:
                    continue

                left = int(min(pt[0] for pt in poly))
                top = int(min(pt[1] for pt in poly))
                right = int(max(pt[0] for pt in poly))
                bottom = int(max(pt[1] for pt in poly))

                if right - left < 10 or bottom - top < 10:
                    continue

                raw_boxes.append({
                    "left": left,
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "text": text
                })

            if not raw_boxes:
                return []

            # Group vertically adjacent lines that belong to the same speech bubble
            sorted_boxes = sorted(raw_boxes, key=lambda b: b['top'])
            grouped = []
            current = sorted_boxes[0]
            for b in sorted_boxes[1:]:
                gap_y = b['top'] - current['bottom']
                height_curr = max(current['bottom'] - current['top'], 15)
                center_curr = (current['left'] + current['right']) / 2
                center_b = (b['left'] + b['right']) / 2
                width_max = max(current['right'] - current['left'], b['right'] - b['left'], 40)

                # Merge condition: vertical gap <= 1.5 * line height AND horizontal alignment close
                if gap_y <= height_curr * 1.8 and abs(center_curr - center_b) <= width_max * 0.8:
                    current['left'] = min(current['left'], b['left'])
                    current['top'] = min(current['top'], b['top'])
                    current['right'] = max(current['right'], b['right'])
                    current['bottom'] = max(current['bottom'], b['bottom'])
                    current['text'] += " " + b['text']
                else:
                    grouped.append({
                        "box": (current['left'], current['top'], current['right'], current['bottom']),
                        "text": current['text'].strip()
                    })
                    current = b
            grouped.append({
                "box": (current['left'], current['top'], current['right'], current['bottom']),
                "text": current['text'].strip()
            })

            return grouped
        except Exception as e:
            print(f"[OCR Error] {e}")
            return []
