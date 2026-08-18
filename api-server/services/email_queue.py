"""Retryable email queue facade with lightweight DLQ bookkeeping."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from services.email_sender import EmailDeliveryError, EmailMessage, EmailSender

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueueResult:
    status: str
    attempts: int
    last_error: str | None = None
    trace_id: str | None = None
    event: dict[str, Any] = field(default_factory=dict)


class EmailQueue:
    def __init__(self, sender: EmailSender | None = None) -> None:
        self.sender = sender or EmailSender()

    async def enqueue(self, message: EmailMessage, *, trace_id: str | None = None) -> QueueResult:
        attempts = 0
        last_error: str | None = None
        for attempts in range(1, 4):
            try:
                await self.sender.send(message)
                event = self._build_event(message, status="sent", attempts=attempts, last_error=None, trace_id=trace_id)
                return QueueResult(status="sent", attempts=attempts, trace_id=trace_id, event=event)
            except EmailDeliveryError as exc:
                last_error = str(exc)
                logger.error("email_queue_attempt_failed attempt=%s error=%s", attempts, type(exc).__name__)
        event = self._build_event(message, status="DLQ", attempts=attempts, last_error=last_error, trace_id=trace_id)
        return QueueResult(status="DLQ", attempts=attempts, last_error=last_error, trace_id=trace_id, event=event)

    def _build_event(self, message: EmailMessage, *, status: str, attempts: int, last_error: str | None, trace_id: str | None) -> dict[str, Any]:
        payload = asdict(message)
        payload.update({
            "status": status,
            "attempts": attempts,
            "last_error": last_error,
            "trace_id": trace_id,
            "created_at": datetime.now(UTC).isoformat(),
        })
        return payload
