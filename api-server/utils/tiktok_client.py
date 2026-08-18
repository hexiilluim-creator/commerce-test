"""
utils/tiktok_client.py — TikTok Business Messaging API client (BLOC 10)
=========================================================================
Envoie des messages via TikTok for Business Messaging.
BYOK par store — access token chiffré Fernet.

Prérequis TikTok :
  - Access Token TikTok for Business (scope : customer_service.read, customer_service.write)
  - Open ID du compte Business TikTok configuré dans le store
  - Webhook /social/tiktok/webhook configuré

⚠️ L'API TikTok Messaging est en accès restreint (partenaires approuvés).
   Par défaut, les appels réels sont désactivés hors production.
"""
from __future__ import annotations

import logging
import os

import httpx

from config import settings

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"


class TikTokClient:
    """Client d'envoi TikTok Business Messaging."""

    def __init__(self, store=None):
        token = None
        open_id = None

        if store is not None:
            enc_token = getattr(store, "tiktok_token_enc", None)
            if enc_token:
                try:
                    token = settings.decrypt(enc_token)
                except Exception as e:
                    logger.warning(
                        "Failed to decrypt TikTok token for store %s: %s",
                        getattr(store, "id", "?"), e,
                    )
            open_id = getattr(store, "tiktok_open_id", None)

        self.access_token = token or ""
        self.open_id = open_id or ""
        self.headers = {
            "Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.open_id)

    @property
    def real_calls_enabled(self) -> bool:
        return bool(
            settings.TIKTOK_ENABLED
            and settings.TIKTOK_ALLOW_REAL_CALLS
            and settings.ENV.lower() == "production"
            and not os.getenv("PYTEST_CURRENT_TEST")
        )

    async def send_text(self, recipient_open_id: str, text: str) -> dict[str, object]:
        """Envoie un message texte à un utilisateur TikTok."""
        if not self.is_configured:
            logger.warning("TikTokClient: token or open_id not configured — message dropped")
            return {"error": "not_configured"}

        payload = {
            "to_user_open_id": recipient_open_id,
            "message_type": "TEXT",
            "content": {"text": text},
        }
        return await self._post(f"{TIKTOK_API_BASE}/customer_service/message/send/", payload)

    async def send_product_card(
        self,
        recipient_open_id: str,
        product_name: str,
        price: float,
        stock: int,
        image_url: str | None = None,
    ) -> dict[str, object]:
        """TikTok ne supporte pas les cartes interactives natives hors marketplace."""
        text = (
            f"🛍️ {product_name}\n"
            f"💰 Prix : {price:.3f} TND\n"
            f"📦 Stock : {stock} unité(s)\n\n"
            f"Tapez OUI pour commander ou NON pour annuler."
        )
        result = await self.send_text(recipient_open_id, text)

        if image_url and self.is_configured:
            try:
                await self.send_image(recipient_open_id, image_url)
            except Exception as e:
                logger.warning("TikTok image send failed (non-critical): %s", e)

        return result

    async def send_image(self, recipient_open_id: str, image_url: str) -> dict[str, object]:
        """Envoie une image via URL publique."""
        if not self.is_configured:
            return {"error": "not_configured"}

        payload = {
            "to_user_open_id": recipient_open_id,
            "message_type": "IMAGE",
            "content": {"image_url": image_url},
        }
        return await self._post(f"{TIKTOK_API_BASE}/customer_service/message/send/", payload)

    async def _post(self, url: str, payload: dict[str, object]) -> dict[str, object]:
        if not settings.TIKTOK_ENABLED:
            logger.info("TikTok disabled — outbound call suppressed")
            return {"status": "disabled", "dry_run": True, "payload": payload}

        if not self.real_calls_enabled:
            logger.info("TikTok dry-run active — outbound call suppressed")
            return {"status": "dry_run", "dry_run": True, "payload": payload}

        async with httpx.AsyncClient(timeout=15.0) as http:
            try:
                r = await http.post(url, json=payload, headers=self.headers)
                r.raise_for_status()
                data = r.json()
                if data.get("code") != 0:
                    logger.error(
                        "TikTok API error code=%s message=%s",
                        data.get("code"), data.get("message"),
                    )
                return data
            except httpx.HTTPStatusError as e:
                logger.error(
                    "TikTok API HTTP error %s: %s",
                    e.response.status_code, e.response.text,
                )
                raise
            except Exception as e:
                logger.error("TikTok send failed: %s", e)
                raise

    async def publish_video(self, video_url: str, caption: str, privacy: str = "PUBLIC_TO_EVERYONE") -> dict[str, object]:
        """
        Publie une vidéo TikTok via Content Posting API.
        Nécessite scope: video.publish
        privacy: PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | FOLLOWER_OF_CREATOR | SELF_ONLY
        """
        if not self.is_configured:
            return {"error": "tiktok_not_configured"}
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                "https://open.tiktokapis.com/v2/post/publish/video/init/",
                headers={**self.headers, "Content-Type": "application/json; charset=UTF-8"},
                json={
                    "post_info": {"title": caption[:150], "privacy_level": privacy, "disable_comment": False},
                    "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            publish_id = data.get("data", {}).get("publish_id")
            return {"ok": True, "publish_id": publish_id, "network": "tiktok"}

    async def publish_photo(self, photo_urls: list[str], caption: str) -> dict[str, object]:
        """Publie un post photo/carrousel TikTok."""
        if not self.is_configured:
            return {"error": "tiktok_not_configured"}
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(
                "https://open.tiktokapis.com/v2/post/publish/content/init/",
                headers={**self.headers, "Content-Type": "application/json; charset=UTF-8"},
                json={
                    "post_info": {"title": caption[:150], "privacy_level": "PUBLIC_TO_EVERYONE"},
                    "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": photo_urls[:35]},
                    "post_mode": "DIRECT_POST",
                    "media_type": "PHOTO",
                },
            )
            resp.raise_for_status()
            return {"ok": True, "publish_id": resp.json().get("data", {}).get("publish_id"), "network": "tiktok"}
