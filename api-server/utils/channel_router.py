"""
utils/channel_router.py — Routeur de canal unifié (BLOC 10)
============================================================
Abstraction unique pour envoyer un message quel que soit le canal :
  whatsapp | instagram | facebook | tiktok

Usage dans ai_agent.py :
    router = ChannelRouter(store, channel="instagram")
    await router.send_text(recipient_id, reply)
    await router.send_product_card(recipient_id, name, price, stock)
"""
from __future__ import annotations

import logging
from typing import Literal

from utils.facebook_client import FacebookClient
from utils.instagram_client import InstagramClient
from utils.tiktok_client import TikTokClient
from utils.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)

Channel = Literal["whatsapp", "instagram", "facebook", "tiktok"]


class ChannelRouter:
    """
    Routeur unifié — délègue les envois au bon client selon le canal.
    Interface identique pour tous les canaux.
    """

    def __init__(self, store, channel: Channel = "whatsapp"):
        self.channel = channel
        self.store = store
        self._client = self._build_client(store, channel)

    def _build_client(self, store, channel: Channel):
        if channel == "whatsapp":
            if hasattr(WhatsAppClient, "from_store"):
                return WhatsAppClient.from_store(store)
            return WhatsAppClient.from_settings()
        elif channel == "instagram":
            return InstagramClient(store)
        elif channel == "facebook":
            return FacebookClient(store)
        elif channel == "tiktok":
            return TikTokClient(store)
        else:
            logger.warning("Unknown channel '%s' — falling back to WhatsApp", channel)
            if hasattr(WhatsAppClient, "from_store"):
                return WhatsAppClient.from_store(store)
            return WhatsAppClient.from_settings()

    @property
    def is_configured(self) -> bool:
        """Vérifie que le client du canal est bien configuré (token présent)."""
        if hasattr(self._client, "is_configured"):
            return self._client.is_configured
        # WhatsAppClient : toujours considéré configuré (fallback global)
        return True

    async def send_text(self, recipient_id: str, text: str) -> dict[str, object]:
        """Envoie un texte — interface unique pour tous les canaux."""
        if not self.is_configured:
            logger.warning(
                "Channel %s not configured for store %s — text message dropped",
                self.channel, getattr(self.store, "id", "?"),
            )
            return {"error": "channel_not_configured", "channel": self.channel}

        try:
            result = await self._client.send_text(recipient_id, text)
            logger.debug("Message sent via %s to %s", self.channel, recipient_id)
            return result
        except Exception as e:
            logger.error(
                "send_text failed on %s for recipient %s: %s",
                self.channel, recipient_id, e,
            )
            raise

    async def send_product_card(
        self,
        recipient_id: str,
        product_name: str,
        price: float,
        stock: int,
        image_url: str | None = None,
    ) -> dict[str, object]:
        """Envoie une carte produit — format adapté au canal."""
        if not self.is_configured:
            logger.warning(
                "Channel %s not configured for store %s — product card dropped",
                self.channel, getattr(self.store, "id", "?"),
            )
            return {"error": "channel_not_configured", "channel": self.channel}

        try:
            return await self._client.send_product_card(
                recipient_id, product_name, price, stock, image_url
            )
        except Exception as e:
            logger.error(
                "send_product_card failed on %s: %s", self.channel, e,
            )
            raise

    async def send_quick_replies(
        self,
        recipient_id: str,
        text: str,
        options: list[str],
    ) -> dict[str, object]:
        """
        Envoie un message avec choix rapides.
        WhatsApp -> boutons interactifs
        Instagram/Facebook -> quick_replies
        TikTok -> message texte avec options listées
        """
        if not self.is_configured:
            return {"error": "channel_not_configured"}

        try:
            if self.channel == "whatsapp":
                buttons = [{"id": o.lower().replace(" ", "_"), "title": o} for o in options[:3]]
                return await self._client.send_interactive_buttons(recipient_id, text, buttons)
            elif self.channel in ("instagram", "facebook"):
                return await self._client.send_quick_replies(recipient_id, text, options)
            elif self.channel == "tiktok":
                # TikTok : texte enrichi avec les options
                options_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(options))
                return await self._client.send_text(recipient_id, f"{text}\n\n{options_text}")
            else:
                return await self.send_text(recipient_id, text)
        except Exception as e:
            logger.error("send_quick_replies failed on %s: %s", self.channel, e)
            raise

    async def mark_as_read(self, message_id_or_sender: str) -> dict[str, object]:
        """
        Marque le message/conversation comme lu.
        WhatsApp -> mark_as_read avec message_id
        Instagram/Facebook -> mark_as_seen avec sender_id
        TikTok -> non supporté nativement
        """
        try:
            if self.channel == "whatsapp":
                return await self._client.mark_as_read(message_id_or_sender)
            elif self.channel in ("instagram", "facebook"):
                return await self._client.mark_as_seen(message_id_or_sender)
            else:
                return {"status": "not_supported", "channel": self.channel}
        except Exception as e:
            logger.warning("mark_as_read failed on %s (non-critical): %s", self.channel, e)
            return {"error": str(e)}
