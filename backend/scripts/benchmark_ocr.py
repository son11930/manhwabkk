"""Run a local, reproducible OCR benchmark over downloaded page images.

Usage: python scripts/benchmark_ocr.py --images ../img --runs 3
The command never fetches URLs and emits only aggregate timing/workload JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.pipeline.ocr import MangaOCREngine
from src.pipeline.ocr_benchmark import summarize_runs


def _image_files(directory: Path) -> tuple[Path, ...]:
    return tuple(sorted(
        (path for path in directory.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}),
        key=lambda path: path.name,
    ))


async def _run_once(paths: tuple[Path, ...], concurrency: int) -> dict[str, float | int]:
    engine = MangaOCREngine()
    semaphore = asyncio.Semaphore(concurrency)

    async def _page(path: Path, index: int) -> dict[str, float | int]:
        queued_at = time.perf_counter()
        async with semaphore:
            started_at = time.perf_counter()
            result = await engine.detect_and_extract(path.read_bytes(), page_index=index)
        metrics = result.metrics
        return {
            "queue_wait_ms": (started_at - queued_at) * 1000,
            "process_ms": (time.perf_counter() - started_at) * 1000,
            "roi_pixels": metrics.roi_pixels,
        }

    started_at = time.perf_counter()
    pages = await asyncio.gather(*(_page(path, index) for index, path in enumerate(paths, start=1)))
    return {
        "stage_wall_ms": (time.perf_counter() - started_at) * 1000,
        "queue_wait_ms": sum(float(page["queue_wait_ms"]) for page in pages) / max(1, len(pages)),
        "process_ms": sum(float(page["process_ms"]) for page in pages) / max(1, len(pages)),
        "roi_pixels": sum(int(page["roi_pixels"]) for page in pages),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--runs", default=3, type=int)
    parser.add_argument("--concurrency", default=4, type=int)
    arguments = parser.parse_args()
    paths = _image_files(arguments.images)
    if not paths:
        raise SystemExit("No image files found")
    if arguments.runs < 1 or arguments.concurrency < 1:
        raise SystemExit("--runs and --concurrency must be positive")
    runs = tuple(asyncio.run(_run_once(paths, arguments.concurrency)) for _ in range(arguments.runs))
    print(json.dumps(summarize_runs(runs), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
