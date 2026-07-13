from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from src.pipeline.contracts import Box


@dataclass(frozen=True)
class RenderInstruction:
    """The sole approved pixel-write operation for one bubble region."""

    region_id: str
    box: Box
    text: str

    def __post_init__(self) -> None:
        left, top, right, bottom = self.box
        if not self.region_id.strip():
            raise ValueError("region_id is required")
        if not self.text.strip():
            raise ValueError("render text is required")
        if right <= left or bottom <= top:
            raise ValueError("render box must have positive area")


def build_render_instructions(instructions: Iterable[RenderInstruction]) -> tuple[RenderInstruction, ...]:
    """Reject duplicate region writes before inpainting or typesetting pixels."""
    result = tuple(instructions)
    seen: set[str] = set()
    for instruction in result:
        if instruction.region_id in seen:
            raise ValueError(f"duplicate region render instruction: {instruction.region_id}")
        seen.add(instruction.region_id)
    return result


def preflight_render_instructions(
    instructions: Iterable[RenderInstruction], *, image_size: tuple[int, int]
) -> tuple[RenderInstruction, ...]:
    """Validate every planned pixel write before inpainting or typesetting.

    This is deliberately a render-layer guard, not an OCR grouping heuristic.
    It preserves adjacent bubbles and rejects only a near-total overlap between
    two *different* regions, which would otherwise paint two translations on
    the same visible bubble.
    """
    result = build_render_instructions(instructions)
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")

    for instruction in result:
        if not _box_within_image(instruction.box, width, height):
            raise ValueError(f"render box outside image bounds: {instruction.region_id}")

    for index, first in enumerate(result):
        for second in result[index + 1 :]:
            if _overlap_ratio_of_smaller_box(first.box, second.box) >= 0.80:
                raise ValueError(
                    "unsafe render collision between distinct regions: "
                    f"{first.region_id}, {second.region_id}"
                )
    return result


def deduplicate_render_instructions(instructions: Iterable[RenderInstruction]) -> tuple[RenderInstruction, ...]:
    """Collapse retry writes for the same stable bubble region only.

    Geometry is deliberately not enough: a small legitimate bubble can be
    nested inside a larger panel or narration box.
    """
    accepted: list[RenderInstruction] = []
    seen: set[str] = set()
    for instruction in instructions:
        if instruction.region_id in seen:
            continue
        seen.add(instruction.region_id)
        accepted.append(instruction)
    return tuple(accepted)


def associate_shifted_region_candidates(instructions: Iterable[RenderInstruction]) -> tuple[RenderInstruction, ...]:
    """Give nearly identical OCR regions the first grouped bubble identity.

    A 0.85 IoU threshold is intentionally conservative: it catches duplicate
    OCR detections that jitter by a few pixels but leaves nearby/nested bubbles
    separate for translation and rendering.
    """
    anchors: list[RenderInstruction] = []
    associated: list[RenderInstruction] = []
    for instruction in instructions:
        anchor = next((item for item in anchors if _iou(instruction.box, item.box) >= 0.85), None)
        if anchor is None:
            anchors.append(instruction)
            associated.append(instruction)
        else:
            associated.append(replace(instruction, region_id=anchor.region_id))
    return tuple(associated)


def _iou(first: Box, second: Box) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    overlap = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - overlap
    return overlap / union if union else 0.0


def _box_within_image(box: Box, width: int, height: int) -> bool:
    left, top, right, bottom = box
    return 0 <= left < right <= width and 0 <= top < bottom <= height


def _overlap_ratio_of_smaller_box(first: Box, second: Box) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    overlap = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    smaller = min(first_area, second_area)
    return overlap / smaller if smaller else 0.0
