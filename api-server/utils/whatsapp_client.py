"""utils/whatsapp_client.py — WhatsApp Business API client wrapper."""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Thin wrapper around the WhatsApp Business API.

    Sends text/media messages via the Meta Graph API.
    """

    GRAPH_API_URL = "https://graph.facebook.com/v19.0"

    def __init__(self, phone_number_id: str | None, access_token: str | None) -> None:
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.is_configured = bool(phone_number_id and access_token)
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        } if access_token else {"Content-Type": "application/json"}

    # ── Factory ────────────────────────────────────────────────────────────────
    @classmethod
    def from_settings(cls) -> WhatsAppClient:
        from config import settings
        return cls(
            phone_number_id=getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None),
            access_token=getattr(settings, "WHATSAPP_ACCESS_TOKEN", None),
        )

    @classmethod
    def from_store(cls, store: Any) -> WhatsAppClient:
        """Build a client from a Store ORM object (per-tenant BYOK)."""
        from config import settings

        token = None
        encrypted_token = getattr(store, "whatsapp_access_token_enc", None)
        if encrypted_token:
            try:
                token = settings.decrypt(encrypted_token)
            except Exception:
                logger.exception(
                    "Failed to decrypt store WhatsApp token for store %s — falling back to global settings",
                    getattr(store, "id", "?"),
                )

        token = token or getattr(settings, "WHATSAPP_ACCESS_TOKEN", None)
        phone_id = getattr(store, "whatsapp_phone_number_id", None) or getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)
        return cls(phone_number_id=phone_id, access_token=token)

    # ── Message sending ────────────────────────────────────────────────────────
    async def send_text(self, to: str, body: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body, "preview_url": False},
        }
        return await self._post(payload)

    async def send_template(self, to: str, template_name: str, language_code: str = "fr",
                            components: list | None = None) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }
        return await self._post(payload)

    async def send_interactive_list(self, to: str, body_text: str,
                                    button_text: str, sections: list) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {"button": button_text, "sections": sections},
            },
        }
        return await self._post(payload)

    async def send_list_message(self, to: str, body: str, sections: list,
                                button: str = "Voir les options") -> dict:
        """Compat alias for older callers expecting send_list_message()."""
        return await self.send_interactive_list(to, body_text=body, button_text=button, sections=sections)

    async def send_interactive_buttons(self, to: str, body_text: str,
                                       buttons: list[dict]) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": buttons},
            },
        }
        return await self._post(payload)

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload)

    async def mark_as_read(self, message_id: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return await self._post(payload)

    async def _post(self, payload: dict) -> dict:
        if not self.is_configured:
            raise RuntimeError("WhatsApp client not configured: missing access token or phone_number_id")

        url = f"{self.GRAPH_API_URL}/{self.phone_number_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=self._headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "WhatsApp API error %s: %s — payload: %s",
                exc.response.status_code,
                exc.response.text,
                payload,
            )
            raise
        except Exception as exc:
            logger.error("WhatsApp API request failed: %s", exc)
            raise
