from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.channel_router import ChannelRouter


def client(configured=True):
    c = MagicMock()
    c.is_configured = configured
    c.send_text = AsyncMock(return_value={"ok": True})
    c.send_product_card = AsyncMock(return_value={"card": True})
    c.send_interactive_buttons = AsyncMock(return_value={"buttons": True})
    c.send_quick_replies = AsyncMock(return_value={"quick": True})
    c.mark_as_read = AsyncMock(return_value={"read": True})
    c.mark_as_seen = AsyncMock(return_value={"seen": True})
    return c


def test_builds_each_supported_client_and_unknown_falls_back():
    store = SimpleNamespace(id=1)
    with patch("utils.channel_router.WhatsAppClient") as wa, patch("utils.channel_router.InstagramClient") as ig, patch("utils.channel_router.FacebookClient") as fb, patch("utils.channel_router.TikTokClient") as tt:
        wa.from_store.return_value = client()
        ig.return_value = client()
        fb.return_value = client()
        tt.return_value = client()
        assert ChannelRouter(store, "whatsapp")._client is wa.from_store.return_value
        assert ChannelRouter(store, "instagram")._client is ig.return_value
        assert ChannelRouter(store, "facebook")._client is fb.return_value
        assert ChannelRouter(store, "tiktok")._client is tt.return_value
        assert ChannelRouter(store, "other")._client is wa.from_store.return_value

@pytest.mark.parametrize("channel", ["instagram", "facebook", "tiktok"])
def test_is_configured_uses_client_property(channel):
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel = channel
    router.store = SimpleNamespace(id=1)
    router._client = client(False)
    assert router.is_configured is False

@pytest.mark.asyncio
async def test_send_text_not_configured_drops_message():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "instagram", SimpleNamespace(id=1), client(False)
    assert await router.send_text("u", "hello") == {"error": "channel_not_configured", "channel": "instagram"}
    router._client.send_text.assert_not_awaited()

@pytest.mark.asyncio
async def test_send_text_and_product_card_delegate():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "facebook", SimpleNamespace(id=1), client()
    assert await router.send_text("u", "hello") == {"ok": True}
    assert await router.send_product_card("u", "shoe", 12.5, 3, "img") == {"card": True}
    router._client.send_text.assert_awaited_once_with("u", "hello")
    router._client.send_product_card.assert_awaited_once_with("u", "shoe", 12.5, 3, "img")

@pytest.mark.asyncio
async def test_send_text_propagates_provider_error():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "facebook", SimpleNamespace(id=1), client()
    router._client.send_text.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError, match="down"):
        await router.send_text("u", "hello")

@pytest.mark.asyncio
async def test_quick_replies_whatsapp_builds_three_buttons():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "whatsapp", SimpleNamespace(id=1), client()
    result = await router.send_quick_replies("u", "Choose", ["One option", "Two", "Three", "Four"])
    assert result == {"buttons": True}
    router._client.send_interactive_buttons.assert_awaited_once_with("u", "Choose", [
        {"id": "one_option", "title": "One option"}, {"id": "two", "title": "Two"}, {"id": "three", "title": "Three"}
    ])

@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["instagram", "facebook"])
async def test_quick_replies_social_delegate(channel):
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = channel, SimpleNamespace(id=1), client()
    assert await router.send_quick_replies("u", "Choose", ["A", "B"]) == {"quick": True}
    router._client.send_quick_replies.assert_awaited_once_with("u", "Choose", ["A", "B"])

@pytest.mark.asyncio
async def test_quick_replies_tiktok_formats_options_as_text():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "tiktok", SimpleNamespace(id=1), client()
    await router.send_quick_replies("u", "Choose", ["A", "B"])
    router._client.send_text.assert_awaited_once_with("u", "Choose\n\n  1. A\n  2. B")

@pytest.mark.asyncio
async def test_quick_replies_not_configured_returns_error():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "tiktok", SimpleNamespace(id=1), client(False)
    assert await router.send_quick_replies("u", "Choose", []) == {"error": "channel_not_configured"}

@pytest.mark.asyncio
@pytest.mark.parametrize("channel,method,expected", [("whatsapp", "mark_as_read", {"read": True}), ("instagram", "mark_as_seen", {"seen": True}), ("facebook", "mark_as_seen", {"seen": True})])
async def test_mark_as_read_routes_supported_channels(channel, method, expected):
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = channel, SimpleNamespace(id=1), client()
    assert await router.mark_as_read("message") == expected
    getattr(router._client, method).assert_awaited_once_with("message")

@pytest.mark.asyncio
async def test_mark_as_read_tiktok_not_supported_and_errors_are_noncritical():
    router = ChannelRouter.__new__(ChannelRouter)
    router.channel, router.store, router._client = "tiktok", SimpleNamespace(id=1), client()
    assert await router.mark_as_read("message") == {"status": "not_supported", "channel": "tiktok"}
    router.channel = "facebook"
    router._client.mark_as_seen.side_effect = RuntimeError("down")
    assert await router.mark_as_read("message") == {"error": "down"}
