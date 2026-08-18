from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from utils.facebook_client import FacebookClient
from utils.instagram_client import InstagramClient
from utils.tiktok_client import TikTokClient


def run(coro):
    return asyncio.run(coro)


def test_facebook_unconfigured_operations_are_safe():
    client = FacebookClient()
    assert client.is_configured is False
    assert run(client.send_text("u", "hello")) == {"error": "not_configured"}
    assert run(client.send_product_card("u", "p", 10.5, 2)) == {"error": "not_configured"}
    assert run(client.send_quick_replies("u", "choose", ["A"])) == {"error": "not_configured"}
    assert run(client.mark_as_seen("u")) == {"error": "not_configured"}
    assert run(client.publish_post("hello")) == {"error": "facebook_not_configured"}
    assert run(client.broadcast_messenger("hello", ["u"])) == {"error": "facebook_not_configured"}


def test_facebook_payloads_are_assertable():
    client = FacebookClient()
    client.access_token = "token"
    client.page_id = "page"
    client.headers["Authorization"] = "Bearer token"
    client._post = AsyncMock(side_effect=[{"ok": 1}, {"ok": 2}, {"ok": 3}, {"ok": 4}])
    assert run(client.send_text("psid", "hello")) == {"ok": 1}
    assert run(client.send_product_card("psid", "Brake", 12.3, 4, "https://img")) == {"ok": 2}
    assert run(client.send_quick_replies("psid", "Pick", ["one", "two"])) == {"ok": 3}
    assert run(client.mark_as_seen("psid")) == {"ok": 4}
    payloads = [call.args[1] for call in client._post.await_args_list]
    assert payloads[0]["message"]["text"] == "hello"
    assert payloads[1]["message"]["attachment"]["payload"]["elements"][0]["image_url"] == "https://img"
    assert len(payloads[2]["message"]["quick_replies"]) == 2
    assert payloads[3]["sender_action"] == "mark_seen"


def test_instagram_unconfigured_operations_are_safe():
    client = InstagramClient()
    assert client.is_configured is False
    assert run(client.send_text("u", "hello")) == {"error": "not_configured"}
    assert run(client.send_product_card("u", "p", 10.5, 2)) == {"error": "not_configured"}
    assert run(client.send_quick_replies("u", "hello", ["Buy"])) == {"error": "not_configured"}


def test_instagram_payloads_are_assertable():
    client = InstagramClient()
    client.access_token = "token"
    client.account_id = "ig-user"
    client._post = AsyncMock(side_effect=[{"text": 1}, {"image": 1}, {"quick": 1}])
    assert run(client.send_text("u", "hello")) == {"text": 1}
    assert run(client.send_product_card("u", "Brake", 12.3, 4)) == {"image": 1}
    assert run(client.send_quick_replies("u", "choose", ["Buy"])) == {"quick": 1}
    first, second, third = [call.args[1] for call in client._post.await_args_list]
    assert first["message"]["text"] == "hello"
    assert "Prix" in second["message"]["text"]
    assert second["message"]["text"].startswith("🛍️")
    assert third["message"]["quick_replies"][0]["title"] == "Buy"


def test_tiktok_unconfigured_operations_are_safe():
    client = TikTokClient()
    assert client.is_configured is False
    assert run(client.send_text("u", "hello")) == {"error": "not_configured"}
    assert run(client.send_image("u", "https://img")) == {"error": "not_configured"}


def test_tiktok_payloads_are_assertable():
    client = TikTokClient()
    client.access_token = "token"
    client.open_id = "business"
    client._post = AsyncMock(side_effect=[{"text": 1}, {"image": 1}])
    assert run(client.send_text("u", "hello")) == {"text": 1}
    assert run(client.send_image("u", "https://img")) == {"image": 1}
    first, second = [call.args[1] for call in client._post.await_args_list]
    assert first["to_user_open_id"] == "u"
    assert first["content"]["text"] == "hello"
    assert second["content"]["image_url"] == "https://img"
