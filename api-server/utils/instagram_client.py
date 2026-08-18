"""
utils/instagram_client.py — Instagram Graph API Messaging client (BLOC 10)
===========================================================================
Envoie des messages via Instagram Messenger (Messaging API).
Pattern identique à WhatsAppClient : BYOK par store, fallback settings globaux.

Prérequis Meta :
  - Token Instagram Graph API avec scope instagram_manage_messages
  - Page connectée à un compte Instagram Business
  - Webhook /social/instagram/webhook configuré et vérifié
"""
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramClient:
    """
    Client d'envoi de messages Instagram Messenger.
    Résout les credentials BYOK par store (token chiffré Fernet).
    """

    def __init__(self, store=None):
        token = None
        account_id = None

        if store is not None:
            enc_token = getattr(store, "instagram_token_enc", None)
            if enc_token:
                try:
                    token = settings.decrypt(enc_token)
                except Exception as e:
                    logger.warning(
                        "Failed to decrypt Instagram token for store %s: %s",
                        getattr(store, "id", "?"), e,
                    )
            account_id = getattr(store, "instagram_account_id", None)

        self.access_token = token or ""
        self.account_id = account_id or ""
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.account_id)

    async def send_text(self, recipient_id: str, text: str) -> dict[str, object]:
        """
        Envoie un message texte à un utilisateur Instagram via son PSID.
        recipient_id = Instagram-scoped user ID (PSID) du client.
        """
        if not self.is_configured:
            logger.warning("InstagramClient: token or account_id not configured — message dropped")
            return {"error": "not_configured"}

        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        }
        return await self._post(f"{GRAPH_API_BASE}/me/messages", payload)

    async def send_product_card(
        self,
        recipient_id: str,
        product_name: str,
        price: float,
        stock: int,
        image_url: str | None = None,
    ) -> dict[str, object]:
        """
        Envoie une carte produit générique en texte formaté.
        Instagram Messenger ne supporte pas les boutons interactifs hors template approuvé.
        """
        text = (
            f"🛍️ {product_name}\n"
            f"💰 Prix : {price:.3f} TND\n"
            f"📦 Stock : {stock} unité(s)\n\n"
            f"Répondez OUI pour commander, NON pour annuler."
        )
        return await self.send_text(recipient_id, text)

    async def send_quick_replies(
        self,
        recipient_id: str,
        text: str,
        quick_replies: list[str],
    ) -> dict[str, object]:
        """
        Envoie un message avec Quick Replies (boutons texte natifs Instagram).
        """
        if not self.is_configured:
            return {"error": "not_configured"}

        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "text": text,
                "quick_replies": [
                    {"content_type": "text", "title": r[:20], "payload": r.upper().replace(" ", "_")}
                    for r in quick_replies[:13]  # Instagram max 13 quick replies
                ],
            },
            "messaging_type": "RESPONSE",
        }
        return await self._post(f"{GRAPH_API_BASE}/me/messages", payload)

    async def mark_as_seen(self, sender_id: str) -> dict[str, object]:
        """Marque le message comme vu (read receipt)."""
        if not self.is_configured:
            return {"error": "not_configured"}
        payload = {
            "recipient": {"id": sender_id},
            "sender_action": "mark_seen",
        }
        return await self._post(f"{GRAPH_API_BASE}/me/messages", payload)

    async def _post(self, url: str, payload: dict) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=15.0) as http:
            try:
                r = await http.post(url, json=payload, headers=self.headers)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Instagram API error %s: %s",
                    e.response.status_code, e.response.text,
                )
                raise
            except Exception as e:
                logger.error("Instagram send failed: %s", e)
                raise

    async def publish_post(self, caption: str, image_url: str) -> dict[str, object]:
        """
        Publie un post Instagram (image + légende) via Content Publishing API.
        Nécessite scope: instagram_content_publish
        Étape 1: créer le media container
        Étape 2: publier le container
        """
        if not self.is_configured:
            return {"error": "instagram_not_configured"}
        async with httpx.AsyncClient(timeout=20.0) as http:
            # Step 1: Create media container
            container_resp = await http.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media",
                headers=self.headers,
                json={"image_url": image_url, "caption": caption, "access_token": self.access_token},
            )
            container_resp.raise_for_status()
            creation_id = container_resp.json().get("id")
            if not creation_id:
                return {"error": "container_creation_failed"}
            # Step 2: Publish
            pub_resp = await http.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media_publish",
                headers=self.headers,
                json={"creation_id": creation_id, "access_token": self.access_token},
            )
            pub_resp.raise_for_status()
            return {"ok": True, "post_id": pub_resp.json().get("id"), "network": "instagram"}

    async def publish_story(self, image_url: str) -> dict[str, object]:
        """Publie une Story Instagram."""
        if not self.is_configured:
            return {"error": "instagram_not_configured"}
        async with httpx.AsyncClient(timeout=20.0) as http:
            container_resp = await http.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media",
                headers=self.headers,
                json={"image_url": image_url, "media_type": "STORIES", "access_token": self.access_token},
            )
            container_resp.raise_for_status()
            creation_id = container_resp.json().get("id")
            pub_resp = await http.post(
                f"{GRAPH_API_BASE}/{self.account_id}/media_publish",
                headers=self.headers,
                json={"creation_id": creation_id, "access_token": self.access_token},
            )
            pub_resp.raise_for_status()
            return {"ok": True, "story_id": pub_resp.json().get("id"), "network": "instagram"}
