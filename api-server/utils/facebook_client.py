"""
utils/facebook_client.py — Facebook Messenger Page Messaging API client (BLOC 10)
==================================================================================
Envoie des messages via Facebook Messenger (Page Messaging API).
Utilise le Page Access Token BYOK par store.

Prérequis Meta :
  - Page Access Token avec scope pages_messaging
  - Page Facebook liée au store
  - Webhook /social/facebook/webhook configuré et vérifié
"""
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class FacebookClient:
    """
    Client d'envoi de messages Facebook Messenger.
    BYOK par store — Page Access Token chiffré Fernet.
    """

    def __init__(self, store=None):
        token = None
        page_id = None

        if store is not None:
            enc_token = getattr(store, "facebook_token_enc", None)
            if enc_token:
                try:
                    token = settings.decrypt(enc_token)
                except Exception as e:
                    logger.warning(
                        "Failed to decrypt Facebook token for store %s: %s",
                        getattr(store, "id", "?"), e,
                    )
            page_id = getattr(store, "facebook_page_id", None)

        self.access_token = token or ""
        self.page_id = page_id or ""
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.page_id)

    async def send_text(self, recipient_id: str, text: str) -> dict[str, object]:
        """
        Envoie un message texte via Facebook Messenger.
        recipient_id = PSID Facebook de l'utilisateur.
        """
        if not self.is_configured:
            logger.warning("FacebookClient: token or page_id not configured — message dropped")
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
        Envoie une carte produit avec boutons Generic Template (Facebook Messenger natif).
        Si image_url fourni, affiche l'image dans la carte.
        """
        if not self.is_configured:
            return {"error": "not_configured"}

        # Generic Template avec boutons
        elements = [{
            "title": product_name,
            "subtitle": f"Prix : {price:.3f} TND | Stock : {stock} unité(s)",
            "buttons": [
                {"type": "postback", "title": "✅ Commander", "payload": "CONFIRM_ORDER"},
                {"type": "postback", "title": "🔄 Alternatives", "payload": "SEE_ALTERNATIVES"},
                {"type": "postback", "title": "❌ Annuler", "payload": "CANCEL"},
            ],
        }]
        if image_url:
            elements[0]["image_url"] = image_url

        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": elements,
                    },
                }
            },
            "messaging_type": "RESPONSE",
        }
        return await self._post(f"{GRAPH_API_BASE}/me/messages", payload)

    async def send_quick_replies(
        self,
        recipient_id: str,
        text: str,
        quick_replies: list[str],
    ) -> dict[str, object]:
        """Envoie un message avec Quick Replies Facebook Messenger."""
        if not self.is_configured:
            return {"error": "not_configured"}

        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "text": text,
                "quick_replies": [
                    {"content_type": "text", "title": r[:20], "payload": r.upper().replace(" ", "_")}
                    for r in quick_replies[:11]  # Facebook max 11 quick replies
                ],
            },
            "messaging_type": "RESPONSE",
        }
        return await self._post(f"{GRAPH_API_BASE}/me/messages", payload)

    async def mark_as_seen(self, sender_id: str) -> dict[str, object]:
        """Envoie le sender_action seen (accusé de lecture)."""
        if not self.is_configured:
            return {"error": "not_configured"}
        payload = {
            "recipient": {"id": sender_id},
            "sender_action": "mark_seen",
        }
        return await self._post(f"{GRAPH_API_BASE}/me/messages", payload)

    async def _post(self, url: str, payload: dict) -> dict[str, object]:
        params = {"access_token": self.access_token}
        async with httpx.AsyncClient(timeout=15.0) as http:
            try:
                r = await http.post(url, json=payload, headers=self.headers, params=params)
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Facebook API error %s: %s",
                    e.response.status_code, e.response.text,
                )
                raise
            except Exception as e:
                logger.error("Facebook send failed: %s", e)
                raise

    async def publish_post(self, message: str, image_url: str | None = None, link: str | None = None) -> dict[str, object]:
        """
        Publie un post sur une Page Facebook.
        Nécessite scope: pages_manage_posts
        """
        if not self.is_configured:
            return {"error": "facebook_not_configured"}
        payload: dict = {"message": message, "access_token": self.access_token}
        endpoint = f"{GRAPH_API_BASE}/{self.page_id}/photos" if image_url else f"{GRAPH_API_BASE}/{self.page_id}/feed"
        if image_url:
            payload["url"] = image_url
        if link and not image_url:
            payload["link"] = link
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(endpoint, headers=self.headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "post_id": data.get("id") or data.get("post_id"), "network": "facebook"}

    async def broadcast_messenger(self, message: str, recipient_psids: list[str]) -> dict[str, object]:
        """
        Envoie un message broadcast à une liste de PSID via Messenger.
        Nécessite: One-Time Notification API ou abonnement actif.
        """
        if not self.is_configured:
            return {"error": "facebook_not_configured"}
        sent, failed = 0, 0
        async with httpx.AsyncClient(timeout=30.0) as http:
            for psid in recipient_psids[:500]:
                try:
                    resp = await http.post(
                        f"{GRAPH_API_BASE}/me/messages",
                        headers=self.headers,
                        params={"access_token": self.access_token},
                        json={"recipient": {"id": psid}, "message": {"text": message}},
                    )
                    if resp.status_code == 200:
                        sent += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
        return {"ok": True, "sent": sent, "failed": failed, "network": "facebook"}
