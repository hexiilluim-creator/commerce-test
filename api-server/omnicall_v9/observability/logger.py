"""Structured logging helpers for isolated OmniCall V9 modules."""

from __future__ import annotations

import logging

from omnicall_v9.observability.context import build_log_context
from omnicall_v9.types.unified_message import UnifiedMessage

LOGGER_NAME = "omnicall_v9"


def get_omnicall_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_pipeline_event(event_name: str, message: UnifiedMessage, **extra: object) -> None:
    """Emit a stable structured log line without mutating the message."""
    logger = get_omnicall_logger()
    payload = build_log_context(message)
    payload.update(extra)
    logger.info(event_name, extra={"omnicall": payload})
