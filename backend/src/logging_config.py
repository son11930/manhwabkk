"""Safe, structured application logging configuration."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_HANDLER_MARKER = "manhwabkk_logging_handler"
_REDACTED_MESSAGE = "[REDACTED SENSITIVE LOG PAYLOAD]"
_SENSITIVE_PAYLOAD_PATTERN = re.compile(
    r"(?:\b(?:authorization|api[_-]?key|token|password|secret|cookie|headers?|dialogue|"
    r"prompt|messages?|translations?)\b\s*[:=])",
    re.IGNORECASE,
)
_SAFE_CONTEXT_KEYS = frozenset({
    "job_id", "stage", "page", "event", "provider", "model",
    "base_passes", "roi_passes", "full_page_passes", "base_pixels", "roi_pixels",
    "base_pass_ms", "component_scan_ms", "roi_recovery_ms", "recovery_trigger",
    "recovery_skipped_reason", "queue_wait_ms", "process_ms", "queue_p50_ms",
    "queue_p95_ms", "process_p50_ms", "process_p95_ms", "recovery_hits", "pages",
    "coverage_verified", "uncovered_components",
})


@dataclass(frozen=True)
class LoggingSettings:
    """Subset of runtime settings used to configure logging."""

    LOG_LEVEL: str
    LOG_FILE_ENABLED: bool
    LOG_FILE_PATH: str
    LOG_FILE_MAX_BYTES: int
    LOG_FILE_BACKUP_COUNT: int


def _safe_text(message: str, max_length: int = 2000) -> str:
    if _SENSITIVE_PAYLOAD_PATTERN.search(message):
        return _REDACTED_MESSAGE
    return message[:max_length]


def _safe_message(record: logging.LogRecord) -> str:
    return _safe_text(record.getMessage())


def _safe_context(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: getattr(record, key)
        for key in _SAFE_CONTEXT_KEYS
        if hasattr(record, key) and isinstance(getattr(record, key), (str, int, float, bool))
    }


class JsonLogFormatter(logging.Formatter):
    """Formats log records as JSON lines while withholding sensitive payloads."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": _safe_message(record),
        }
        payload.update(_safe_context(record))
        if record.exc_info:
            payload["exception"] = _safe_text(self.formatException(record.exc_info), max_length=4000)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _create_console_handler() -> logging.StreamHandler[Any]:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    setattr(handler, _HANDLER_MARKER, True)
    return handler


def _create_file_handler(config: LoggingSettings) -> RotatingFileHandler:
    log_path = Path(config.LOG_FILE_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=config.LOG_FILE_MAX_BYTES,
        backupCount=config.LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(JsonLogFormatter())
    setattr(handler, _HANDLER_MARKER, True)
    return handler


def configure_logging(config: LoggingSettings) -> None:
    """Configure console logs and optionally persistent rotating JSON logs."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    for handler in list(root_logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root_logger.removeHandler(handler)
            handler.close()

    root_logger.addHandler(_create_console_handler())
    if config.LOG_FILE_ENABLED:
        root_logger.addHandler(_create_file_handler(config))
