"""Small, dependency-free aggregation helpers for reproducible OCR benchmarks."""

from __future__ import annotations

from statistics import median
from typing import Mapping, Sequence


def percentile(values: Sequence[float], quantile: float) -> float:
    """Nearest-rank percentile; deterministic for short local benchmark runs."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile + 0.999999)))
    return ordered[index]


def summarize_runs(runs: Sequence[Mapping[str, float]]) -> dict[str, float | int]:
    """Return safe aggregate metrics; individual dialogue is never accepted here."""
    stage_wall = tuple(float(run.get("stage_wall_ms", 0.0)) for run in runs)
    queue_wait = tuple(float(run.get("queue_wait_ms", 0.0)) for run in runs)
    process = tuple(float(run.get("process_ms", 0.0)) for run in runs)
    return {
        "runs": len(runs),
        "stage_wall_ms_median": float(median(stage_wall)) if stage_wall else 0.0,
        "queue_wait_ms_p50": percentile(queue_wait, 0.5),
        "queue_wait_ms_p95": percentile(queue_wait, 0.95),
        "process_ms_p50": percentile(process, 0.5),
        "process_ms_p95": percentile(process, 0.95),
        "roi_pixels_total": int(sum(float(run.get("roi_pixels", 0.0)) for run in runs)),
    }
