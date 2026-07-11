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
            result = result or []

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

            # Comic lettering often uses a small, stylized font that the normal
            # detector misses entirely. Retry on an enlarged, contrast-normalized
            # image and merge only distinct regions into the same OCR evidence.
            enhanced_scale = 1.0
            enhanced_result = []
            enhanced_scale = min(3.0, max(1.0, 1800.0 / max(image.shape[:2])))
            enhanced = cv2.resize(
                image,
                (0, 0),
                fx=enhanced_scale,
                fy=enhanced_scale,
                interpolation=cv2.INTER_CUBIC,
            )
            enhanced_gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
            enhanced_gray = cv2.adaptiveThreshold(
                enhanced_gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9,
            )
            enhanced_response = self.ocr_engine(cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR))
            enhanced_result = enhanced_response[0] if isinstance(enhanced_response, tuple) else enhanced_response

            def overlapping_index(candidate: dict[str, Any]) -> int | None:
                for index, existing in enumerate(lines):
                    left = max(candidate["left"], existing["left"])
                    top = max(candidate["top"], existing["top"])
                    right = min(candidate["right"], existing["right"])
                    bottom = min(candidate["bottom"], existing["bottom"])
                    overlap = max(0, right - left) * max(0, bottom - top)
                    candidate_area = (candidate["right"] - candidate["left"]) * (candidate["bottom"] - candidate["top"])
                    existing_area = (existing["right"] - existing["left"]) * (existing["bottom"] - existing["top"])
                    union = candidate_area + existing_area - overlap
                    if overlap / max(union, 1) >= 0.7:
                        return index
                return None

            for item in enhanced_result or []:
                polygon, raw_text, raw_confidence = item[0], str(item[1]).strip(), float(item[2])
                if raw_confidence < 0.4 or len(raw_text) < 2:
                    continue
                candidate = {
                    "left": int(min(point[0] for point in polygon) / (scale * enhanced_scale)),
                    "top": int(min(point[1] for point in polygon) / (scale * enhanced_scale)),
                    "right": int(max(point[0] for point in polygon) / (scale * enhanced_scale)),
                    "bottom": int(max(point[1] for point in polygon) / (scale * enhanced_scale)),
                    "text": raw_text,
                    "confidence": raw_confidence,
                }
                if candidate["right"] - candidate["left"] < 10 or candidate["bottom"] - candidate["top"] < 10:
                    continue
                existing_index = overlapping_index(candidate)
                if existing_index is None:
                    lines.append(candidate)
                elif candidate["confidence"] > lines[existing_index]["confidence"]:
                    lines[existing_index] = candidate

            if not lines:
                return []

            grouped: list[dict[str, Any]] = []
            current = dict(sorted(lines, key=lambda line: (line["top"], line["left"]))[0])
            current["raw_lines"] = [current["text"]]
            current["confidences"] = [current["confidence"]]
            for line in sorted(lines, key=lambda value: (value["top"], value["left"]))[1:]:
                vertical_gap = line["top"] - current["bottom"]
                current_height = max(current["bottom"] - current["top"], 15)
                line_height = max(line["bottom"] - line["top"], 15)
                ref_height = max(current_height, line_height)
                current_center = (current["left"] + current["right"]) / 2
                line_center = (line["left"] + line["right"]) / 2
                max_width = max(current["right"] - current["left"], line["right"] - line["left"], 40)
                horizontal_overlap = max(current["left"], line["left"]) < min(current["right"], line["right"])
                same_bubble = (vertical_gap <= ref_height * 1.8) and (
                    horizontal_overlap or abs(current_center - line_center) <= max_width * 0.75
                )
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
