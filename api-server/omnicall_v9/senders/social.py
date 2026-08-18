"""omnicall_v9/senders/social.py — Senders sociaux V9 : Instagram, Facebook, TikTok (BLOC 10).

VERSION: v25 (BLOC 10)
"""
from __future__ import annotations

import logging
import time

from omnicall_v9.senders.base import AgentReply, BaseSender, ReplyKind, SendResult, register_sender
from omnicall_v9.types.unified_message import ChannelType
from utils.tiktok_client import TikTokClient

logger = logging.getLogger("omnicall_v9.senders.social")


# ── Instagram ─────────────────────────────────────────────────────────────────

class InstagramV9Sender(BaseSender):
    """Sender Instagram Messenger API V9 (BLOC 10).

    Utilise utils/instagram_client.py.
    Supporte : texte, image, quick replies (boutons simples).
    """

    channel = ChannelType.INSTAGRAM

    async def send(self, reply: AgentReply) -> SendResult:
        start = time.perf_counter()
        try:
            from utils.instagram_client import InstagramClient
            client = InstagramClient.from_settings()
            to = reply.recipient_id

            if reply.kind == ReplyKind.TEXT:
                result = await client.send_text(to, reply.text or "")
            elif reply.kind == ReplyKind.IMAGE:
                result = await client.send_image(to, reply.media_url or "", caption=reply.media_caption)
            elif reply.kind == ReplyKind.INTERACTIVE:
                # Instagram Messenger supporte les quick replies
                result = await client.send_quick_replies(
                    to,
                    text=reply.interactive_body or reply.text or "",
                    quick_replies=[
                        {"content_type": "text", "title": b.get("title", ""), "payload": b.get("id", "")}
                        for b in reply.interactive_buttons[:3]  # IG limite à 3
                    ],
                )
            else:
                # Fallback texte pour les kinds non supportés sur IG
                text = reply.text or f"[{reply.kind}]"
                result = await client.send_text(to, text)

            latency_ms = (time.perf_counter() - start) * 1000
            logger.info("omnicall_v9.ig_sender.sent store_id=%s latency=%.1fms",
                        reply.store_id, latency_ms)
            return SendResult(
                success=True,
                channel=ChannelType.INSTAGRAM,
                recipient_id=to,
                provider_message_id=result.get("message_id"),
                latency_ms=round(latency_ms, 1),
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error("omnicall_v9.ig_sender.failed store_id=%s error=%s",
                         reply.store_id, exc)
            return SendResult(
                success=False,
                channel=ChannelType.INSTAGRAM,
                recipient_id=reply.recipient_id,
                error=str(exc),
                latency_ms=round(latency_ms, 1),
            )


# ── Facebook ──────────────────────────────────────────────────────────────────

class FacebookV9Sender(BaseSender):
    """Sender Facebook Messenger V9 (BLOC 10).

    Utilise utils/facebook_client.py.
    Supporte : texte, image, boutons génériques (generic template).
    """

    channel = ChannelType.FACEBOOK

    async def send(self, reply: AgentReply) -> SendResult:
        start = time.perf_counter()
        try:
            from utils.facebook_client import FacebookClient
            client = FacebookClient.from_settings()
            to = reply.recipient_id

            if reply.kind == ReplyKind.TEXT:
                result = await client.send_text(to, reply.text or "")

            elif reply.kind == ReplyKind.IMAGE:
                result = await client.send_attachment(
                    to,
                    attachment_type="image",
                    url=reply.media_url or "",
                )

            elif reply.kind == ReplyKind.INTERACTIVE:
                # Facebook Messenger : boutons ou quick replies
                if reply.interactive_type == "button":
                    result = await client.send_buttons(
                        to,
                        text=reply.interactive_body or reply.text or "",
                        buttons=[
                            {"type": "postback", "title": b.get("title", ""), "payload": b.get("id", "")}
                            for b in reply.interactive_buttons[:3]  # FB limite à 3
                        ],
                    )
                else:
                    result = await client.send_text(to, reply.interactive_body or reply.text or "")
            else:
                result = await client.send_text(to, reply.text or f"[{reply.kind}]")

            latency_ms = (time.perf_counter() - start) * 1000
            logger.info("omnicall_v9.fb_sender.sent store_id=%s latency=%.1fms",
                        reply.store_id, latency_ms)
            return SendResult(
                success=True,
                channel=ChannelType.FACEBOOK,
                recipient_id=to,
                provider_message_id=result.get("message_id"),
                latency_ms=round(latency_ms, 1),
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error("omnicall_v9.fb_sender.failed store_id=%s error=%s",
                         reply.store_id, exc)
            return SendResult(
                success=False,
                channel=ChannelType.FACEBOOK,
                recipient_id=reply.recipient_id,
                error=str(exc),
                latency_ms=round(latency_ms, 1),
            )


# ── TikTok ────────────────────────────────────────────────────────────────────

class TikTokV9Sender(BaseSender):
    """Sender TikTok Business Messaging V9 (BLOC 10).

    TikTok Business API supporte : texte uniquement en direct message.
    Images et boutons → fallback texte.

    NOTE: l'API TikTok DM est en accès restreint (Business Partner seulement).
    En l'absence d'accès, le sender log et retourne un SendResult success=False
    sans lever d'exception (comportement graceful degradation).
    """

    channel = ChannelType.TIKTOK

    async def send(self, reply: AgentReply) -> SendResult:
        start = time.perf_counter()
        try:
            client = TikTokClient.from_settings()
            to = reply.recipient_id

            # TikTok DM: texte seulement, tous les autres kinds → texte
            text = reply.text or reply.interactive_body or f"[{reply.kind}]"
            # Pour les INTERACTIVE, ajouter les options en texte brut
            if reply.kind == ReplyKind.INTERACTIVE and reply.interactive_buttons:
                options = "\n".join(
                    f"{i+1}. {b.get('title', '')}"
                    for i, b in enumerate(reply.interactive_buttons)
                )
                text = f"{text}\n\n{options}"

            result = await client.send_text(to, text)

            latency_ms = (time.perf_counter() - start) * 1000
            logger.info("omnicall_v9.tiktok_sender.sent store_id=%s latency=%.1fms",
                        reply.store_id, latency_ms)
            return SendResult(
                success=True,
                channel=ChannelType.TIKTOK,
                recipient_id=to,
                provider_message_id=result.get("message_id"),
                latency_ms=round(latency_ms, 1),
            )

        except NotImplementedError:
            logger.warning(
                "omnicall_v9.tiktok_sender.not_implemented store_id=%s — "
                "TikTok DM API requires Business Partner access",
                reply.store_id,
            )
            return SendResult(
                success=False,
                channel=ChannelType.TIKTOK,
                recipient_id=reply.recipient_id,
                error="TikTok DM API not available (Business Partner required)",
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.error("omnicall_v9.tiktok_sender.failed store_id=%s error=%s",
                         reply.store_id, exc)
            return SendResult(
                success=False,
                channel=ChannelType.TIKTOK,
                recipient_id=reply.recipient_id,
                error=str(exc),
                latency_ms=round(latency_ms, 1),
            )


# Auto-enregistrement
register_sender(InstagramV9Sender())
register_sender(FacebookV9Sender())
register_sender(TikTokV9Sender())
