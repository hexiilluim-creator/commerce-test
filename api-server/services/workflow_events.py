"""services/workflow_events.py — Persistance des événements de workflow.

Persistance des événements de workflow.
Insère dans workflow_events si disponible, sinon log structuré (graceful degradation).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def record_workflow_event(
    db: AsyncSession,
    *,
    workflow_type: str,
    status: str,
    provider: str | None = None,
    channel: str | None = None,
    tenant_id: int | None = None,
    external_event_id: str | None = None,
    message_id: str | None = None,
    signature_status: str | None = None,
    payload_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    retryable: bool = False,
    dlq_name: str | None = None,
) -> None:
    """Enregistre un événement de workflow (webhook received/queued/rejected/replayed).

    Insère dans workflow_events si la table existe. Sinon, log structuré (graceful degradation).
    """
    try:
        from models.database import WorkflowEvent
        event = WorkflowEvent(
            workflow_type=workflow_type,
            status=status,
            provider=provider,
            channel=channel,
            tenant_id=tenant_id,
            external_event_id=external_event_id,
            message_id=message_id,
            signature_status=signature_status,
            payload_json=payload_json or {},
            error_message=error_message,
            retryable=retryable,
            dlq_name=dlq_name,
        )
        db.add(event)
        # Note: commit is handled by the caller
    except (ImportError, AttributeError, Exception):
        # Graceful degradation: log but don't block the webhook flow
        logger.info(
            "workflow_event.logged type=%s status=%s channel=%s tenant=%s msg_id=%s",
            workflow_type, status, channel, tenant_id, message_id,
            exc_info=False,
        )
        if error_message:
            logger.warning("workflow_event.error %s: %s", workflow_type, error_message)
