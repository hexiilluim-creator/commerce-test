"""omnicall_v9/senders/whatsapp.py — Sender WhatsApp V9 (BLOC 10).

Wrapper V9 autour de utils/whatsapp_client.py.
Gère : texte, templates, boutons interactifs, images.
Retry exponentiel (3 tentatives), logging structuré, jamais de throw externe.

VERSION: v25 (BLOC 10)
"""
from __future__ import annotations

import logging
import time

from omnicall_v9.senders.base import AgentReply, BaseSender, ReplyKind, SendResult, register_sender
from omnicall_v9.types.unified_message import ChannelType

logger = logging.getLogger("omnicall_v9.senders.whatsapp")

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # secondes, exponentiel


class WhatsAppV9Sender(BaseSender):
    """Sender WhatsApp BLOC 10.

    Utilise WhatsAppClient.from_store() si le store est fourni (BYOK),
    sinon WhatsAppClient.from_settings() (credentials globales).
    """

    channel = ChannelType.WHATSAPP

    def __init__(self, store: object | None = None) -> None:
        self._store = store

    def _get_client(self):
        from utils.whatsapp_client import WhatsAppClient
        if self._store:
            return WhatsAppClient.from_store(self._store)
        return WhatsAppClient.from_settings()

    async def send(self, reply: AgentReply) -> SendResult:
        start = time.perf_counter()
        last_error: str | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = await self._dispatch(reply)
                latency_ms = (time.perf_counter() - start) * 1000

                logger.info(
                    "omnicall_v9.wa_sender.sent",
                    extra={
                        "kind": reply.kind,
                        "recipient": reply.recipient_id[-4:] + "****",
                        "store_id": reply.store_id,
                        "attempt": attempt,
                        "latency_ms": round(latency_ms, 1),
                        "provider_msg_id": result.get("messages", [{}])[0].get("id"),
                    },
                )

                return SendResult(
                    success=True,
                    channel=ChannelType.WHATSAPP,
                    recipient_id=reply.recipient_id,
                    provider_message_id=result.get("messages", [{}])[0].get("id"),
                    latency_ms=round(latency_ms, 1),
                )

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "omnicall_v9.wa_sender.retry",
                    extra={
                        "attempt": attempt,
                        "max_retries": _MAX_RETRIES,
                        "error": last_error,
                        "store_id": reply.store_id,
                    },
                )
                if attempt < _MAX_RETRIES:
                    import asyncio
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** (attempt - 1)))

        latency_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "omnicall_v9.wa_sender.failed",
            extra={"store_id": reply.store_id, "error": last_error, "latency_ms": round(latency_ms, 1)},
        )
        return SendResult(
            success=False,
            channel=ChannelType.WHATSAPP,
            recipient_id=reply.recipient_id,
            error=last_error,
            latency_ms=round(latency_ms, 1),
        )

    async def _dispatch(self, reply: AgentReply) -> dict:
        """Dispatch vers le bon type d'envoi selon reply.kind."""
        client = self._get_client()
        to = reply.recipient_id

        if reply.kind == ReplyKind.TEXT:
            if not reply.text:
                raise ValueError("AgentReply.text is required for TEXT kind")
            return await client.send_text(to, reply.text)

        if reply.kind == ReplyKind.TEMPLATE:
            if not reply.template_name:
                raise ValueError("AgentReply.template_name is required for TEMPLATE kind")
            return await client.send_template(
                to,
                reply.template_name,
                language_code=reply.template_language,
                components=reply.template_components or None,
            )

        if reply.kind == ReplyKind.INTERACTIVE:
            if not reply.interactive_body:
                raise ValueError("AgentReply.interactive_body required for INTERACTIVE kind")
            if reply.interactive_type == "list":
                return await client.send_list_message(
                    to,
                    body=reply.interactive_body,
                    sections=reply.interactive_buttons,
                )
            # Défaut : boutons
            return await client.send_interactive_buttons(
                to,
                body=reply.interactive_body,
                buttons=reply.interactive_buttons,
            )

        if reply.kind == ReplyKind.IMAGE:
            if not reply.media_url:
                raise ValueError("AgentReply.media_url required for IMAGE kind")
            return await client.send_image(
                to, reply.media_url, caption=reply.media_caption
            )

        raise ValueError(f"Unsupported ReplyKind for WhatsApp: {reply.kind}")


# Auto-enregistrement au chargement du module
register_sender(WhatsAppV9Sender())
