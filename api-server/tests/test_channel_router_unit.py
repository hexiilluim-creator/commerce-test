from __future__ import annotations

from types import SimpleNamespace

import pytest

import utils.channel_router as channel_router_module
from utils.channel_router import ChannelRouter


class _FakeClient:
    def __init__(self, name: str, is_configured: bool = True) -> None:
        self.name = name
        self.is_configured = is_configured
        self.calls: list[tuple] = []

    async def send_text(self, recipient_id: str, text: str) -> dict[str, object]:
        self.calls.append(("send_text", recipient_id, text))
        return {"client": self.name, "recipient_id": recipient_id, "text": text}

    async def send_product_card(
        self,
        recipient_id: str,
        product_name: str,
        price: float,
        stock: int,
        image_url: str | None = None,
    ) -> dict[str, object]:
        self.calls.append(("send_product_card", recipient_id, product_name, price, stock, image_url))
        return {"client": self.name, "product_name": product_name}

    async def send_interactive_buttons(
        self,
        recipient_id: str,
        text: str,
        buttons: list[dict[str, str]],
    ) -> dict[str, object]:
        self.calls.append(("send_interactive_buttons", recipient_id, text, buttons))
        return {"buttons": buttons}

    async def send_quick_replies(
        self,
        recipient_id: str,
        text: str,
        options: list[str],
    ) -> dict[str, object]:
        self.calls.append(("send_quick_replies", recipient_id, text, options))
        return {"options": options}

    async def mark_as_read(self, message_id: str) -> dict[str, object]:
        self.calls.append(("mark_as_read", message_id))
        return {"status": "read", "message_id": message_id}

    async def mark_as_seen(self, sender_id: str) -> dict[str, object]:
        self.calls.append(("mark_as_seen", sender_id))
        return {"status": "seen", "sender_id": sender_id}


class _FakeWhatsAppClient:
    from_store_calls: list[object] = []
    from_settings_calls = 0

    @classmethod
    def reset(cls) -> None:
        cls.from_store_calls = []
        cls.from_settings_calls = 0

    @classmethod
    def from_store(cls, store) -> _FakeClient:
        cls.from_store_calls.append(store)
        return _FakeClient("whatsapp")

    @classmethod
    def from_settings(cls) -> _FakeClient:
        cls.from_settings_calls += 1
        return _FakeClient("whatsapp-settings")


def _factory(name: str, *, configured: bool = True):
    def _build(store) -> _FakeClient:
        return _FakeClient(name, is_configured=configured)

    return _build


@pytest.fixture(autouse=True)
def patch_channel_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeWhatsAppClient.reset()
    monkeypatch.setattr(channel_router_module, "WhatsAppClient", _FakeWhatsAppClient)
    monkeypatch.setattr(channel_router_module, "InstagramClient", _factory("instagram"))
    monkeypatch.setattr(channel_router_module, "FacebookClient", _factory("facebook"))
    monkeypatch.setattr(channel_router_module, "TikTokClient", _factory("tiktok"))


def test_channel_router_builds_whatsapp_client_from_store() -> None:
    store = SimpleNamespace(id=99)

    router = ChannelRouter(store, channel="whatsapp")

    assert _FakeWhatsAppClient.from_store_calls == [store]
    assert isinstance(router._client, _FakeClient)
    assert router._client.name == "whatsapp"


@pytest.mark.asyncio
async def test_channel_router_drops_messages_when_channel_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(channel_router_module, "InstagramClient", _factory("instagram", configured=False))
    router = ChannelRouter(SimpleNamespace(id=5), channel="instagram")

    result = await router.send_text("usr-1", "bonjour")

    assert result == {"error": "channel_not_configured", "channel": "instagram"}


@pytest.mark.asyncio
async def test_channel_router_formats_whatsapp_quick_replies() -> None:
    router = ChannelRouter(SimpleNamespace(id=1), channel="whatsapp")

    result = await router.send_quick_replies(
        "recipient-1",
        "Choisissez",
        ["Livraison rapide", "Retrait magasin", "Annuler", "Extra"],
    )

    assert result == {
        "buttons": [
            {"id": "livraison_rapide", "title": "Livraison rapide"},
            {"id": "retrait_magasin", "title": "Retrait magasin"},
            {"id": "annuler", "title": "Annuler"},
        ]
    }


@pytest.mark.asyncio
async def test_channel_router_formats_tiktok_quick_replies_as_text() -> None:
    router = ChannelRouter(SimpleNamespace(id=2), channel="tiktok")

    result = await router.send_quick_replies("tt-user", "Options", ["Un", "Deux"])

    assert result == {
        "client": "tiktok",
        "recipient_id": "tt-user",
        "text": "Options\n\n  1. Un\n  2. Deux",
    }


@pytest.mark.asyncio
async def test_channel_router_mark_as_read_returns_not_supported_for_tiktok() -> None:
    router = ChannelRouter(SimpleNamespace(id=3), channel="tiktok")

    result = await router.mark_as_read("msg-9")

    assert result == {"status": "not_supported", "channel": "tiktok"}
