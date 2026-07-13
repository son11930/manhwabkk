from src.pipeline.ocr_benchmark import percentile, summarize_runs


def test_benchmark_summary_uses_median_and_p95() -> None:
    summary = summarize_runs((
        {"stage_wall_ms": 100.0, "queue_wait_ms": 2.0, "process_ms": 90.0, "roi_pixels": 10},
        {"stage_wall_ms": 120.0, "queue_wait_ms": 4.0, "process_ms": 100.0, "roi_pixels": 12},
        {"stage_wall_ms": 110.0, "queue_wait_ms": 3.0, "process_ms": 95.0, "roi_pixels": 11},
    ))

    assert summary["runs"] == 3
    assert summary["stage_wall_ms_median"] == 110.0
    assert summary["queue_wait_ms_p95"] >= 3.0
    assert summary["roi_pixels_total"] == 33


def test_percentile_handles_empty_and_single_values() -> None:
    assert percentile((), 0.95) == 0.0
    assert percentile((7.0,), 0.95) == 7.0
