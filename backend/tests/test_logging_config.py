import json
import logging
from pathlib import Path

from src.config import Settings
from src.logging_config import JsonLogFormatter, configure_logging


def _settings_for_log_file(log_file: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "LOG_FILE_ENABLED": True,
        "LOG_FILE_PATH": str(log_file),
        "LOG_FILE_MAX_BYTES": 512,
        "LOG_FILE_BACKUP_COUNT": 2,
    }
    return Settings(**(defaults | overrides))


def test_json_log_formatter_redacts_sensitive_payloads_and_dialogue() -> None:
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="pipeline.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='headers={"Authorization": "Bearer top-secret"}, dialogue="entire chapter"',
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "[REDACTED SENSITIVE LOG PAYLOAD]"
    assert "top-secret" not in formatter.format(record)
    assert "entire chapter" not in formatter.format(record)


def test_json_log_formatter_redacts_sensitive_exception_details() -> None:
    formatter = JsonLogFormatter()
    try:
        raise RuntimeError("Authorization=Bearer top-secret")
    except RuntimeError:
        record = logging.LogRecord(
            name="pipeline.worker",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="translation failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )

    rendered = formatter.format(record)

    assert "top-secret" not in rendered


def test_configure_logging_writes_rotating_json_lines_and_keeps_console(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "pipeline.jsonl"
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    for handler in previous_handlers:
        root_logger.removeHandler(handler)

    try:
        configure_logging(_settings_for_log_file(log_file))
        logging.getLogger("pipeline.worker").info(
            "OCR page complete",
            extra={"job_id": "job-123", "roi_passes": 2, "roi_pixels": 2400},
        )
        for handler in root_logger.handlers:
            handler.flush()

        payload = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert payload["event"] == "OCR page complete"
        assert payload["roi_passes"] == 2
        assert payload["roi_pixels"] == 2400
        assert payload["job_id"] == "job-123"
        assert payload["logger"] == "pipeline.worker"
        assert any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers)
        assert any(handler.__class__.__name__ == "RotatingFileHandler" for handler in root_logger.handlers)
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            root_logger.addHandler(handler)


def test_configure_logging_can_disable_file_writing(tmp_path: Path) -> None:
    log_file = tmp_path / "disabled.jsonl"
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    for handler in previous_handlers:
        root_logger.removeHandler(handler)

    try:
        configure_logging(_settings_for_log_file(log_file, LOG_FILE_ENABLED=False))

        assert not log_file.exists()
        assert not any(handler.__class__.__name__ == "RotatingFileHandler" for handler in root_logger.handlers)
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            root_logger.addHandler(handler)
