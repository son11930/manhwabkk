from __future__ import annotations

from typing import Any, List
import asyncio

import cv2
import numpy as np

from src.pipeline.contracts import OCRSegment


class MangaOCREngine:
    """Extracts ordered OCR segments while retaining line-level evidence."""

    def __init__(self):
        import os
        for env_key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            if env_key not in os.environ:
                os.environ[env_key] = "2"
        try:
            cv2.setNumThreads(2)
        except Exception:
            pass
        try:
            from rapidocr_onnxruntime import RapidOCR

            self.ocr_engine = RapidOCR()
            self.is_ready = True
        except Exception:
            self.ocr_engine = None
            self.is_ready = False

    @staticmethod
    def _is_glued_text(text: str) -> bool:
        return any(len(token) >= 12 for token in text.split() if token.isupper())

    def detect_and_extract_sync(self, image_bytes: bytes, page_index: int = 0) -> List[OCRSegment]:
        if not self.is_ready or not image_bytes:
            return []

        try:
            image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                return []

            scale = 1.0
            if image.shape[1] > 2400:
                scale = 2400.0 / image.shape[1]
                image = cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

            response = self.ocr_engine(image)
            result = response[0] if isinstance(response, tuple) else response
            if not result:
                return []

            lines: list[dict[str, Any]] = []
            for item in result:
                polygon, raw_text, raw_confidence = item[0], str(item[1]).strip(), float(item[2])
                if raw_confidence < 0.4 or len(raw_text) < 2:
                    continue
                left = int(min(point[0] for point in polygon) / scale)
                top = int(min(point[1] for point in polygon) / scale)
                right = int(max(point[0] for point in polygon) / scale)
                bottom = int(max(point[1] for point in polygon) / scale)
                if right - left < 10 or bottom - top < 10:
                    continue
                lines.append({
                    "left": left,
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "text": raw_text,
                    "confidence": raw_confidence,
                })

            if not lines:
                return []

            grouped: list[dict[str, Any]] = []
            current = dict(sorted(lines, key=lambda line: (line["top"], line["left"]))[0])
            current["raw_lines"] = [current["text"]]
            current["confidences"] = [current["confidence"]]
            for line in sorted(lines, key=lambda value: (value["top"], value["left"]))[1:]:
                vertical_gap = line["top"] - current["bottom"]
                current_height = max(current["bottom"] - current["top"], 15)
                current_center = (current["left"] + current["right"]) / 2
                line_center = (line["left"] + line["right"]) / 2
                max_width = max(current["right"] - current["left"], line["right"] - line["left"], 40)
                same_bubble = vertical_gap <= current_height * 1.2 and abs(current_center - line_center) <= max_width * 0.5
                if same_bubble:
                    current["left"] = min(current["left"], line["left"])
                    current["top"] = min(current["top"], line["top"])
                    current["right"] = max(current["right"], line["right"])
                    current["bottom"] = max(current["bottom"], line["bottom"])
                    current["raw_lines"].append(line["text"])
                    current["confidences"].append(line["confidence"])
                else:
                    grouped.append(current)
                    current = dict(line)
                    current["raw_lines"] = [line["text"]]
                    current["confidences"] = [line["confidence"]]
            grouped.append(current)

            segments: list[OCRSegment] = []
            for reading_order, item in enumerate(sorted(grouped, key=lambda value: (value["top"], value["left"])), start=1):
                raw_lines = tuple(item["raw_lines"])
                source_text = " ".join(raw_lines).strip()
                segments.append(OCRSegment(
                    segment_id=f"{page_index}:{reading_order}",
                    page_index=page_index,
                    reading_order=reading_order,
                    box=(item["left"], item["top"], item["right"], item["bottom"]),
                    raw_lines=raw_lines,
                    source_text=source_text,
                    confidence=min(item["confidences"]),
                ))
            return segments
        except Exception as error:
            print(f"[OCR Error] {error}")
            return []

    async def detect_and_extract(self, image_bytes: bytes, page_index: int = 0) -> List[OCRSegment]:
        return await asyncio.to_thread(self.detect_and_extract_sync, image_bytes, page_index)
