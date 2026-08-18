from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.whatsapp_client import WhatsAppClient


def _install_fake_config(monkeypatch: pytest.MonkeyPatch, *, token: str, phone_id: str, decrypt):
    fake_config = ModuleType("config")
    fake_config.settings = SimpleNamespace(
        WHATSAPP_ACCESS_TOKEN=token,
        WHATSAPP_PHONE_NUMBER_ID=phone_id,
        decrypt=decrypt,
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)


def test_from_store_decrypts_encrypted_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_config(
        monkeypatch,
        token="global-token",
        phone_id="global-phone",
        decrypt=lambda value: f"decrypted::{value}",
    )

    store = SimpleNamespace(
        id=7,
        whatsapp_access_token_enc="cipher-store-token",
        whatsapp_phone_number_id="phone-store-1",
    )

    client = WhatsAppClient.from_store(store)

    assert client.access_token == "decrypted::cipher-store-token"
    assert client.phone_number_id == "phone-store-1"
    assert client.is_configured is True


def test_from_store_falls_back_to_global_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_config(
        monkeypatch,
        token="global-token",
        phone_id="global-phone",
        decrypt=lambda value: value,
    )

    store = SimpleNamespace(id=11, whatsapp_access_token_enc=None, whatsapp_phone_number_id=None)

    client = WhatsAppClient.from_store(store)

    assert client.access_token == "global-token"
    assert client.phone_number_id == "global-phone"
    assert client.is_configured is True


def test_send_list_message_and_send_image_use_expected_payloads() -> None:
    client = WhatsAppClient(phone_number_id="phone-1", access_token="token-1")
    client._post = AsyncMock(side_effect=[{"ok": "list"}, {"ok": "image"}])

    async def _run() -> None:
        await client.send_list_message(
            "21600000000",
            body="Catalogue",
            sections=[{"title": "Produits", "rows": [{"id": "p1", "title": "T-shirt"}]}],
        )
        await client.send_image("21600000000", "https://cdn.example.com/p1.png", caption="Produit 1")

    asyncio.run(_run())

    first_payload = client._post.await_args_list[0].args[0]
    second_payload = client._post.await_args_list[1].args[0]

    assert first_payload["type"] == "interactive"
    assert first_payload["interactive"]["type"] == "list"
    assert first_payload["interactive"]["action"]["button"] == "Voir les options"
    assert second_payload == {
        "messaging_product": "whatsapp",
        "to": "21600000000",
        "type": "image",
        "image": {"link": "https://cdn.example.com/p1.png", "caption": "Produit 1"},
    }


def test_post_raises_when_client_not_configured() -> None:
    client = WhatsAppClient(phone_number_id=None, access_token=None)

    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(client._post({"type": "text"}))
