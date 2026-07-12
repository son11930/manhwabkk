from __future__ import annotations

from typing import Any, List
import asyncio
import re
import math

import cv2
import numpy as np

from src.pipeline.contracts import OCRSegment


class MangaOCREngine:
    """Extracts ordered OCR segments while retaining line-level evidence."""

    def __init__(self):
        import os
        for env_key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            if env_key not in os.environ:
                os.environ[env_key] = "1"
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        try:
            cv2.setNumThreads(1)
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

    @staticmethod
    def _polygon_angle(polygon: tuple | list) -> int:
        points = MangaOCREngine._ordered_quad(polygon)
        if points is None:
            return 0
        angle = math.degrees(math.atan2(float(points[1][1] - points[0][1]), float(points[1][0] - points[0][0])))
        return int(round(((angle + 90) % 180) - 90))

    @staticmethod
    def _ordered_quad(polygon: tuple | list) -> np.ndarray | None:
        """Validate and canonicalize detector points before perspective warping."""
        points = np.asarray(polygon, dtype=np.float32)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            return None
        sums = points.sum(axis=1)
        diffs = np.diff(points, axis=1).reshape(-1)
        indices = (int(np.argmin(sums)), int(np.argmin(diffs)), int(np.argmax(sums)), int(np.argmax(diffs)))
        if len(set(indices)) != 4:
            return None
        ordered = points[list(indices)]
        if not cv2.isContourConvex(ordered.reshape((-1, 1, 2))) or abs(cv2.contourArea(ordered)) < 100:
            return None
        return ordered

    @staticmethod
    def _candidate_score(text: str, confidence: float) -> float:
        letters = len(re.findall(r"[A-Za-z]", text or ""))
        preserved_marks = len(re.findall(r"['-]|!{2,}|\?", text or ""))
        return float(confidence) + min(letters, 40) * 0.002 + preserved_marks * 0.03

    @staticmethod
    def _needs_italic_recovery(lines: list[dict[str, Any]]) -> bool:
        """Detect likely stylized/comic lettering without trusting confidence alone."""
        if not lines:
            return False
        confidences = [float(line["confidence"]) for line in lines]
        return (
            min(confidences) < 0.65
            or sum(confidences) / len(confidences) < 0.82
        )

    @staticmethod
    def _has_uncovered_text_component(image: np.ndarray, lines: list[dict[str, Any]], scale: float) -> bool:
        """Find likely lettering on a light bubble background outside OCR boxes."""
        if not lines:
            return False
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        local_background = cv2.GaussianBlur(gray, (31, 31), 0)
        dark_on_light = cv2.inRange(gray, 0, 105) & cv2.inRange(local_background, 185, 255)
        merged = cv2.dilate(dark_on_light, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5)), iterations=1)
        count, _, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
        covered_boxes = [
            (
                int(line["left"] * scale) - 12,
                int(line["top"] * scale) - 12,
                int(line["right"] * scale) + 12,
                int(line["bottom"] * scale) + 12,
            )
            for line in lines
        ]
        for index in range(1, count):
            left, top, width, height, area = stats[index]
            if (
                area < 80
                or width < 18
                or height < 12
                or width / max(height, 1) < 1.4
                or width > image.shape[1] * 0.55
                or left <= 8
                or top <= 8
                or left + width >= image.shape[1] - 8
                or top + height >= image.shape[0] - 8
            ):
                continue
            right, bottom = left + width, top + height
            overlaps_existing = any(
                max(0, min(right, box_right) - max(left, box_left))
                * max(0, min(bottom, box_bottom) - max(top, box_top)) > 0
                for box_left, box_top, box_right, box_bottom in covered_boxes
            )
            if not overlaps_existing:
                return True
        return False

    @staticmethod
    def _inverse_shear_polygon(
        polygon: Any, shear: float, upscale: float, x_offset: float = 0.0,
    ) -> tuple[tuple[float, float], ...]:
        """Map OCR polygons from an upscaled/sheared image back to page coordinates."""
        return tuple(
            ((float(point[0]) - x_offset - shear * float(point[1])) / upscale, float(point[1]) / upscale)
            for point in polygon
        )

    @staticmethod
    def _deskew_roi(image: np.ndarray, polygon: tuple | list) -> np.ndarray | None:
        points = MangaOCREngine._ordered_quad(polygon)
        if points is None:
            return None
        image_height, image_width = image.shape[:2]
        if np.any(points[:, 0] < 0) or np.any(points[:, 1] < 0) or np.any(points[:, 0] >= image_width) or np.any(points[:, 1] >= image_height):
            return None
        width_top = np.linalg.norm(points[1] - points[0])
        width_bottom = np.linalg.norm(points[2] - points[3])
        height_left = np.linalg.norm(points[3] - points[0])
        height_right = np.linalg.norm(points[2] - points[1])
        width, height = int(round(max(width_top, width_bottom))), int(round(max(height_left, height_right)))
        if width < 10 or height < 10 or width / max(height, 1) > 12 or width * height > 350_000:
            return None
        target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
        matrix = cv2.getPerspectiveTransform(points, target)
        roi = cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return cv2.copyMakeBorder(roi, 12, 12, 12, 12, cv2.BORDER_REPLICATE)

    @staticmethod
    def _group_lines(lines: list[dict[str, Any]], page_width: int, page_height: int) -> list[dict[str, Any]]:
        """Group neighbouring text lines inside the same speech bubble."""
        grouped: list[dict[str, Any]] = []
        max_area = max(page_width * page_height * 0.25, 1)
        for line in sorted(lines, key=lambda value: (value["top"], value["left"])):
            matched_group: dict[str, Any] | None = None
            matched_score = float("-inf")
            for group in grouped:
                vertical_gap = line["top"] - group["last_bottom"]
                prev_line_height = max(group["last_bottom"] - group["last_top"], 15)
                curr_line_height = max(line["bottom"] - line["top"], 15)
                group_center = (group["left"] + group["right"]) / 2
                line_center = (line["left"] + line["right"]) / 2
                max_width = max(group["right"] - group["left"], line["right"] - line["left"], 40)
                overlap_width = max(0, min(group["right"], line["right"]) - max(group["left"], line["left"]))
                same_bubble = (
                    -curr_line_height * 0.8 <= vertical_gap <= max(prev_line_height * 1.6, curr_line_height * 1.6, 55)
                    and (overlap_width > 0 or abs(group_center - line_center) <= max_width * 0.75)
                )
                left, top = min(group["left"], line["left"]), min(group["top"], line["top"])
                right, bottom = max(group["right"], line["right"]), max(group["bottom"], line["bottom"])
                score = overlap_width - abs(group_center - line_center)
                if same_bubble and (right - left) * (bottom - top) <= max_area and score > matched_score:
                    matched_group = group
                    matched_score = score
            if matched_group is None:
                matched_group = dict(line)
                matched_group["last_top"] = line["top"]
                matched_group["last_bottom"] = line["bottom"]
                matched_group["raw_lines"] = []
                matched_group["confidences"] = []
                grouped.append(matched_group)
            matched_group["left"] = min(matched_group["left"], line["left"])
            matched_group["top"] = min(matched_group["top"], line["top"])
            matched_group["right"] = max(matched_group["right"], line["right"])
            matched_group["bottom"] = max(matched_group["bottom"], line["bottom"])
            matched_group["last_top"] = line["top"]
            matched_group["last_bottom"] = line["bottom"]
            matched_group["raw_lines"].append(line["text"])
            matched_group["confidences"].append(line["confidence"])
        return grouped

    def detect_and_extract_sync(self, image_bytes: bytes, page_index: int = 0) -> List[OCRSegment]:
        if not self.is_ready or not image_bytes:
            return []

        try:
            image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                return []
            original_height, original_width = image.shape[:2]

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
                    "polygon": tuple(tuple(float(value) for value in point) for point in polygon),
                })

            # Comic lettering can be slanted. Repair only a few low-confidence
            # detected ROIs; a full-page enhanced pass is reserved for no text.
            enhanced_scale = 1.0
            enhanced_result = []
            needs_recovery = (
                not lines
                or self._needs_italic_recovery(lines)
                or self._has_uncovered_text_component(image, lines, scale)
            )
            if lines and needs_recovery:
                for line in sorted((item for item in lines if item["confidence"] < 0.65), key=lambda item: item["confidence"])[:4]:
                    angle = self._polygon_angle(line["polygon"])
                    if not 2 <= abs(angle) <= 20:
                        continue
                    roi = self._deskew_roi(image, line["polygon"])
                    if roi is None:
                        continue
                    roi_response = self.ocr_engine(roi)
                    roi_results = roi_response[0] if isinstance(roi_response, tuple) else roi_response
                    if not roi_results:
                        continue
                    best = max(roi_results, key=lambda item: float(item[2]))
                    candidate_text, candidate_confidence = str(best[1]).strip(), float(best[2])
                    if candidate_text and candidate_confidence >= line["confidence"] + 0.10 and self._candidate_score(candidate_text, candidate_confidence) > self._candidate_score(line["text"], line["confidence"]):
                        line["text"] = candidate_text
                        line["confidence"] = candidate_confidence
            elif needs_recovery:
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
                    same_text = self._normalize_ocr_reading(candidate["text"]).upper() == self._normalize_ocr_reading(existing["text"]).upper()
                    if same_text and overlap / max(min(candidate_area, existing_area), 1) >= 0.4:
                        return index
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

            # Italic lettering is commonly sheared while its baseline remains
            # horizontal, so polygon-angle deskew cannot discover it. Use a
            # small bounded page variant set only for suspicious OCR evidence.
            if lines and needs_recovery:
                upscale = 2.0
                upscaled = cv2.resize(image, (0, 0), fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
                for shear in (-0.12, -0.22):
                    x_offset = max(0, int(np.ceil(-shear * upscaled.shape[0])))
                    width = upscaled.shape[1] + int(np.ceil(abs(shear) * upscaled.shape[0]))
                    matrix = np.float32([[1, shear, x_offset], [0, 1, 0]])
                    variant = cv2.warpAffine(
                        upscaled,
                        matrix,
                        (width, upscaled.shape[0]),
                        flags=cv2.INTER_CUBIC,
                        borderMode=cv2.BORDER_REPLICATE,
                    )
                    variant_response = self.ocr_engine(variant)
                    variant_result = variant_response[0] if isinstance(variant_response, tuple) else variant_response
                    for item in variant_result or []:
                        polygon, raw_text, raw_confidence = item[0], str(item[1]).strip(), float(item[2])
                        if raw_confidence < 0.4 or len(raw_text) < 2:
                            continue
                        points = self._inverse_shear_polygon(polygon, shear, upscale, x_offset)
                        candidate = {
                            "left": int(min(point[0] for point in points) / scale),
                            "top": int(min(point[1] for point in points) / scale),
                            "right": int(max(point[0] for point in points) / scale),
                            "bottom": int(max(point[1] for point in points) / scale),
                            "text": raw_text,
                            "confidence": raw_confidence,
                        }
                        if candidate["right"] - candidate["left"] < 10 or candidate["bottom"] - candidate["top"] < 10:
                            continue
                        existing_index = overlapping_index(candidate)
                        if existing_index is None:
                            lines.append(candidate)
                        elif self._candidate_score(candidate["text"], candidate["confidence"]) > self._candidate_score(lines[existing_index]["text"], lines[existing_index]["confidence"]):
                            lines[existing_index] = candidate

            if not lines:
                return []

            grouped = self._group_lines(lines, original_width, original_height)
            return [
                OCRSegment(
                    segment_id=f"{page_index}:{reading_order}", page_index=page_index, reading_order=reading_order,
                    box=(item["left"], item["top"], item["right"], item["bottom"]),
                    raw_lines=tuple(item["raw_lines"]),
                    source_text=self._normalize_ocr_reading(" ".join(item["raw_lines"])),
                    confidence=min(item["confidences"]),
                )
                for reading_order, item in enumerate(sorted(grouped, key=lambda value: (value["top"], value["left"])), start=1)
            ]
        except Exception as error:
            print(f"[OCR Error] {error}")
            return []

    @staticmethod
    def _normalize_ocr_reading(text: str) -> str:
        """Universal OCR text normalization for all manga/manhwa."""
        cleaned = text.strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    async def detect_and_extract(self, image_bytes: bytes, page_index: int = 0) -> List[OCRSegment]:
        return await asyncio.to_thread(self.detect_and_extract_sync, image_bytes, page_index)
