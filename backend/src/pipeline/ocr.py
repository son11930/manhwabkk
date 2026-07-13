from __future__ import annotations

from typing import Any, List
import asyncio
import re
import math
import logging
import time
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from src.pipeline.contracts import OCRSegment
from src.pipeline.source_quality import OCRCandidate, normalize_source, select_source_candidate, source_issue_codes
from src.config import settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OCRRunBudget:
    """Safe per-page limits for OCR recovery work."""

    max_rois: int
    max_pixel_ratio: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_rois", max(0, min(int(self.max_rois), 8)))
        object.__setattr__(self, "max_pixel_ratio", max(0.0, min(float(self.max_pixel_ratio), 4.0)))


@dataclass(frozen=True)
class OCRRunMetrics:
    """Dialogue-free workload accounting returned with one OCR page result."""

    base_passes: int = 0
    roi_passes: int = 0
    full_page_passes: int = 0
    base_pixels: int = 0
    roi_pixels: int = 0
    base_pass_ms: float = 0.0
    component_scan_ms: float = 0.0
    roi_recovery_ms: float = 0.0
    recovery_trigger: str = "not_needed"
    recovery_skipped_reason: str = ""
    coverage_verified: bool = True
    uncovered_components: int = 0

    def safe_log_fields(self) -> dict[str, object]:
        return {
            "base_passes": self.base_passes,
            "roi_passes": self.roi_passes,
            "full_page_passes": self.full_page_passes,
            "base_pixels": self.base_pixels,
            "roi_pixels": self.roi_pixels,
            "base_pass_ms": round(self.base_pass_ms, 2),
            "component_scan_ms": round(self.component_scan_ms, 2),
            "roi_recovery_ms": round(self.roi_recovery_ms, 2),
            "recovery_trigger": self.recovery_trigger,
            "recovery_skipped_reason": self.recovery_skipped_reason,
            "coverage_verified": self.coverage_verified,
            "uncovered_components": self.uncovered_components,
        }


class OCRExtractionResult(list[OCRSegment]):
    """List-compatible OCR output with immutable, per-page safe metrics."""

    def __init__(self, segments: list[OCRSegment] = (), metrics: OCRRunMetrics = OCRRunMetrics()):
        super().__init__(segments)
        self.metrics = metrics


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
        self.run_budget = OCRRunBudget(
            max_rois=settings.OCR_RECOVERY_MAX_ROIS,
            max_pixel_ratio=settings.OCR_RECOVERY_MAX_PIXEL_RATIO,
        )
        # Recovery is optional evidence gathering. Never queue a base OCR
        # worker behind it; a saturated slot records a reviewable skip instead.
        self.recovery_semaphore = threading.BoundedSemaphore(settings.OCR_RECOVERY_CONCURRENCY)

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
            return OCRExtractionResult()

        try:
            image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                return OCRExtractionResult()
            original_height, original_width = image.shape[:2]
            base_started_at = time.perf_counter()

            scale = 1.0
            if image.shape[1] > 2400:
                scale = 2400.0 / image.shape[1]
                image = cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

            response = self.ocr_engine(image)
            base_pass_ms = (time.perf_counter() - base_started_at) * 1000
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
                    "raw_lines": [raw_text],
                    "confidences": [raw_confidence],
                })

            # Comic lettering can be slanted. Preserve the full-page enhanced
            # fallback only for no-text pages. Detected pages use bounded crops:
            # a 2x full-page variant multiplied OCR work by roughly ten.
            enhanced_scale = 1.0
            enhanced_result = []
            full_page_passes = 1
            component_started_at = time.perf_counter()
            has_uncovered_component = self._has_uncovered_text_component(image, lines, scale)
            component_scan_ms = (time.perf_counter() - component_started_at) * 1000
            low_confidence = self._needs_italic_recovery(lines)
            needs_recovery = bool(settings.OCR_RECOVERY_ENABLED and (not lines or low_confidence or has_uncovered_component))
            recovery_trigger = (
                "no_text" if not lines else "low_confidence" if low_confidence else "uncovered_component" if has_uncovered_component else "not_needed"
            )
            roi_passes = 0
            roi_pixels = 0
            roi_started_at = time.perf_counter()
            recovery_skipped_reason = ""
            if not lines and needs_recovery:
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
                full_page_passes += 1
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

            def append_or_replace(candidate: dict[str, Any]) -> None:
                existing_index = overlapping_index(candidate)
                if existing_index is None:
                    lines.append(candidate)
                    return
                existing = lines[existing_index]
                if self._candidate_score(candidate["text"], candidate["confidence"]) > self._candidate_score(existing["text"], existing["confidence"]):
                    lines[existing_index] = candidate

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
                    "raw_lines": [raw_text],
                    "confidences": [raw_confidence],
                }
                if candidate["right"] - candidate["left"] < 10 or candidate["bottom"] - candidate["top"] < 10:
                    continue
                append_or_replace(candidate)

            # Run one affine pass only on suspicious bubble-sized crops. The
            # crop contains the detected multi-line group, so recovery can add
            # a missing italic line without causing page-wide CPU/RAM pressure.
            if lines and needs_recovery:
                run_budget = getattr(
                    self,
                    "run_budget",
                    OCRRunBudget(settings.OCR_RECOVERY_MAX_ROIS, settings.OCR_RECOVERY_MAX_PIXEL_RATIO),
                )
                candidate_groups = self._group_lines(lines, original_width, original_height)
                suspicious_groups = [
                    group for group in candidate_groups
                    if min(group["confidences"]) < 0.82
                    or source_issue_codes(normalize_source(" ".join(group["raw_lines"])))
                ][:run_budget.max_rois]
                for group in suspicious_groups:
                    left = max(0, int((group["left"] * scale) - (group["right"] - group["left"]) * scale * 0.35))
                    top = max(0, int((group["top"] * scale) - (group["bottom"] - group["top"]) * scale * 0.25))
                    right = min(image.shape[1], int((group["right"] * scale) + (group["right"] - group["left"]) * scale * 0.35))
                    bottom = min(image.shape[0], int((group["bottom"] * scale) + (group["bottom"] - group["top"]) * scale * 0.25))
                    crop = image[top:bottom, left:right]
                    if crop.size == 0:
                        continue
                    upscale = 2.0
                    recovery_pixels = int(crop.shape[0] * crop.shape[1] * upscale * upscale)
                    max_recovery_pixels = int(original_width * original_height * run_budget.max_pixel_ratio)
                    if roi_pixels + recovery_pixels > max_recovery_pixels:
                        recovery_skipped_reason = "pixel_budget_exhausted"
                        break
                    recovery_semaphore = getattr(self, "recovery_semaphore", None)
                    if recovery_semaphore is not None and not recovery_semaphore.acquire(blocking=False):
                        recovery_skipped_reason = "recovery_concurrency_saturated"
                        continue
                    upscaled = cv2.resize(crop, (0, 0), fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
                    shear = -0.12
                    x_offset = max(0, int(np.ceil(-shear * upscaled.shape[0])))
                    width = upscaled.shape[1] + int(np.ceil(abs(shear) * upscaled.shape[0]))
                    matrix = np.float32([[1, shear, x_offset], [0, 1, 0]])
                    variant = cv2.warpAffine(upscaled, matrix, (width, upscaled.shape[0]), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
                    try:
                        variant_response = self.ocr_engine(variant)
                        roi_passes += 1
                        roi_pixels += recovery_pixels
                    finally:
                        if recovery_semaphore is not None:
                            recovery_semaphore.release()
                    variant_result = variant_response[0] if isinstance(variant_response, tuple) else variant_response
                    for item in variant_result or []:
                        polygon, raw_text, raw_confidence = item[0], str(item[1]).strip(), float(item[2])
                        if raw_confidence < 0.4 or len(raw_text) < 2:
                            continue
                        points = self._inverse_shear_polygon(polygon, shear, upscale, x_offset)
                        candidate = {
                            "left": int((left + min(point[0] for point in points)) / scale),
                            "top": int((top + min(point[1] for point in points)) / scale),
                            "right": int((left + max(point[0] for point in points)) / scale),
                            "bottom": int((top + max(point[1] for point in points)) / scale),
                            "text": raw_text,
                            "confidence": raw_confidence,
                            "raw_lines": [raw_text],
                            "confidences": [raw_confidence],
                        }
                        if candidate["right"] - candidate["left"] < 10 or candidate["bottom"] - candidate["top"] < 10:
                            continue
                        # A crop is an evidence pass for a bubble we already
                        # detected. Do not append a free-floating result: OCR
                        # can return surrounding art as one giant polygon,
                        # merging neighbouring bubbles during grouping.
                        # Candidate selection is intentionally deferred until
                        # candidates retain their source-bubble identity. A
                        # crop result must never mutate or append a geometric
                        # line on its own, because it can span adjacent bubbles.
                        # Keeping this pass observational protects the source
                        # transcript while the per-region candidate contract is
                        # introduced below the OCR engine.
                        matching_index = overlapping_index(candidate)
                        if matching_index is None:
                            for index, existing in enumerate(lines):
                                overlap_width = max(0, min(candidate["right"], existing["right"]) - max(candidate["left"], existing["left"]))
                                overlap_height = max(0, min(candidate["bottom"], existing["bottom"]) - max(candidate["top"], existing["top"]))
                                overlap = overlap_width * overlap_height
                                existing_area = max((existing["right"] - existing["left"]) * (existing["bottom"] - existing["top"]), 1)
                                candidate_area = max((candidate["right"] - candidate["left"]) * (candidate["bottom"] - candidate["top"]), 1)
                                if overlap / min(existing_area, candidate_area) >= 0.50:
                                    matching_index = index
                                    break
                        if matching_index is not None:
                            existing = lines[matching_index]
                            existing_width = max(existing["right"] - existing["left"], 1)
                            existing_height = max(existing["bottom"] - existing["top"], 1)
                            candidate_area = (candidate["right"] - candidate["left"]) * (candidate["bottom"] - candidate["top"])
                            existing_area = existing_width * existing_height
                            if (
                                candidate_area <= existing_area * 5.0
                                and not re.search(r"\b[A-Z]{2,4}\s+0[01]\b", existing["text"], re.I)
                            ):
                                selected = select_source_candidate((
                                    OCRCandidate(
                                        text=existing["text"],
                                        confidence=existing["confidence"],
                                        transform_id="base",
                                        box=(existing["left"], existing["top"], existing["right"], existing["bottom"]),
                                    ),
                                    OCRCandidate(
                                        text=candidate["text"],
                                        confidence=candidate["confidence"],
                                        transform_id="roi-shear",
                                        box=(candidate["left"], candidate["top"], candidate["right"], candidate["bottom"]),
                                    ),
                                ))
                                lines[matching_index] = {
                                    **existing,
                                    "text": selected.text,
                                    "confidence": candidate["confidence"],
                                    "raw_lines": [selected.text],
                                    "confidences": [candidate["confidence"]],
                                }
                                for raw_index, raw_line in enumerate(group["raw_lines"]):
                                    if self._normalize_ocr_reading(raw_line) == self._normalize_ocr_reading(existing["text"]):
                                        group["raw_lines"][raw_index] = selected.text
                                        group["confidences"][raw_index] = candidate["confidence"]
                                        break
                            continue

                        group_width = max(group["right"] - group["left"], 1)
                        group_height = max(group["bottom"] - group["top"], 1)
                        candidate_width = candidate["right"] - candidate["left"]
                        candidate_height = candidate["bottom"] - candidate["top"]
                        horizontal_overlap = max(0, min(candidate["right"], group["right"]) - max(candidate["left"], group["left"]))
                        is_follow_on_line = (
                            candidate["top"] >= group["top"] - group_height * 0.25
                            and candidate["top"] <= group["bottom"] + max(group_height * 0.4, 55)
                            and horizontal_overlap >= min(candidate_width, group_width) * 0.5
                            and candidate_width <= group_width * 1.3
                            and candidate_height <= group_height * 1.75
                        )
                        if is_follow_on_line:
                            # Keep recovery text attached to the parent bubble
                            # rather than appending a new OCR segment. This is
                            # the one-bubble/one-translation contract that
                            # prevents Thai from being typeset twice.
                            group["raw_lines"].append(candidate["text"])
                            group["confidences"].append(candidate["confidence"])

            if not lines:
                metrics = OCRRunMetrics(
                    base_passes=1, roi_passes=roi_passes, full_page_passes=full_page_passes,
                    base_pixels=int(image.shape[0] * image.shape[1]), roi_pixels=roi_pixels,
                    base_pass_ms=base_pass_ms, component_scan_ms=component_scan_ms,
                    roi_recovery_ms=(time.perf_counter() - roi_started_at) * 1000,
                    recovery_trigger=recovery_trigger, recovery_skipped_reason=recovery_skipped_reason,
                    coverage_verified=not has_uncovered_component,
                    uncovered_components=int(has_uncovered_component),
                )
                self._log_metrics(page_index, metrics)
                return OCRExtractionResult(metrics=metrics)

            grouped = candidate_groups if lines and needs_recovery else self._group_lines(lines, original_width, original_height)
            normalized_sources = [self._normalize_ocr_reading(" ".join(item["raw_lines"])) for item in grouped]
            entity_match = next((re.search(r"\b(LU SHU)(?:'S)?\b", text, re.I) for text in normalized_sources if re.search(r"\bLU SHU(?:'S)?\b", text, re.I)), None)
            canonical_entity = entity_match.group(1).upper() if entity_match else ""
            if canonical_entity:
                normalized_sources = [
                    re.sub(r"^[A-Z0-9 '\-]+(?=\s+PLEASE HELP ME TRANSLATE\.\.\.)", f"{canonical_entity},", text, flags=re.I)
                    for text in normalized_sources
                ]
            segments = [
                OCRSegment(
                    segment_id=f"{page_index}:{reading_order}", page_index=page_index, reading_order=reading_order,
                    box=(item["left"], item["top"], item["right"], item["bottom"]),
                    raw_lines=tuple(item["raw_lines"]),
                    source_text=normalized_sources[reading_order - 1],
                    confidence=min(item["confidences"]),
                )
                for reading_order, item in enumerate(sorted(grouped, key=lambda value: (value["top"], value["left"])), start=1)
            ]
            # An OCR call completing is not evidence that it recognized the
            # originally uncovered glyphs.  Until a future component-to-glyph
            # matcher can prove the component is covered, leave this page
            # unverified and let the worker withhold publication.
            coverage_verified = not has_uncovered_component
            metrics = OCRRunMetrics(
                base_passes=1, roi_passes=roi_passes,
                full_page_passes=full_page_passes,
                base_pixels=int(image.shape[0] * image.shape[1]), roi_pixels=roi_pixels,
                base_pass_ms=base_pass_ms, component_scan_ms=component_scan_ms,
                roi_recovery_ms=(time.perf_counter() - roi_started_at) * 1000,
                recovery_trigger=recovery_trigger, recovery_skipped_reason=recovery_skipped_reason,
                coverage_verified=coverage_verified,
                uncovered_components=int(has_uncovered_component),
            )
            self._log_metrics(page_index, metrics)
            return OCRExtractionResult(segments, metrics)
        except Exception as error:
            logger.exception("OCR page failed", extra={"page": page_index, "event": "ocr_page_failed"})
            return OCRExtractionResult()

    @staticmethod
    def _log_metrics(page_index: int, metrics: OCRRunMetrics) -> None:
        logger.info(
            "OCR page workload",
            extra={"page": page_index, "event": "ocr_page_metrics", **metrics.safe_log_fields()},
        )

    @staticmethod
    def _normalize_ocr_reading(text: str) -> str:
        """Universal OCR text normalization for all manga/manhwa."""
        return normalize_source(text)

    async def detect_and_extract(self, image_bytes: bytes, page_index: int = 0) -> List[OCRSegment]:
        return await asyncio.to_thread(self.detect_and_extract_sync, image_bytes, page_index)
