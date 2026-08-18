from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from utils.facebook_client import FacebookClient, GRAPH_API_BASE


def store(token="enc", page="page-1"):
    return SimpleNamespace(id=1, facebook_token_enc=token, facebook_page_id=page)


def fake_http(response=None, side_effect=None):
    http = AsyncMock()
    http.__aenter__.return_value = http
    if side_effect is not None:
        http.post.side_effect = side_effect
    else:
        http.post.return_value = response
    return http


def test_configuration_and_decrypt_failure():
    with patch("utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: "token")):
        c = FacebookClient(store())
    assert c.is_configured is True
    assert c.headers["Authorization"] == "Bearer token"
    with patch("utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: (_ for _ in ()).throw(RuntimeError("bad")))):
        c = FacebookClient(store())
    assert c.is_configured is False
    assert FacebookClient(None).is_configured is False

@pytest.mark.asyncio
async def test_unconfigured_operations_return_safe_errors():
    c = FacebookClient(None)
    assert await c.send_text("u", "x") == {"error": "not_configured"}
    assert await c.send_product_card("u", "x", 1, 0) == {"error": "not_configured"}
    assert await c.send_quick_replies("u", "x", []) == {"error": "not_configured"}
    assert await c.mark_as_seen("u") == {"error": "not_configured"}
    assert await c.publish_post("x") == {"error": "facebook_not_configured"}
    assert await c.broadcast_messenger("x", []) == {"error": "facebook_not_configured"}

@pytest.mark.asyncio
async def test_send_text_posts_expected_payload():
    response = httpx.Response(200, json={"message_id": "m"}, request=httpx.Request("POST", "https://x"))
    http = fake_http(response)
    with patch("utils.facebook_client.httpx.AsyncClient", return_value=http), patch(
        "utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: "token")
    ):
        result = await FacebookClient(store()).send_text("user", "hello")
    assert result == {"message_id": "m"}
    kwargs = http.post.await_args.kwargs
    assert kwargs["json"] == {"recipient": {"id": "user"}, "message": {"text": "hello"}, "messaging_type": "RESPONSE"}

@pytest.mark.asyncio
async def test_product_card_and_quick_replies_payload_limits():
    response = httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", "https://x"))
    http = fake_http(response)
    with patch("utils.facebook_client.httpx.AsyncClient", return_value=http), patch(
        "utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: "token")
    ):
        c = FacebookClient(store())
        await c.send_product_card("u", "shoe", 2.5, 4, "https://img")
        await c.send_quick_replies("u", "choose", [str(i) for i in range(15)])
    product = http.post.await_args_list[0].kwargs["json"]
    assert product["message"]["attachment"]["payload"]["elements"][0]["image_url"] == "https://img"
    quick = http.post.await_args_list[1].kwargs["json"]["message"]["quick_replies"]
    assert len(quick) == 11
    assert len(quick[0]["title"]) <= 20

@pytest.mark.asyncio
async def test_mark_as_seen_and_post_publish_image_and_link():
    response = httpx.Response(200, json={"id": "post-1"}, request=httpx.Request("POST", "https://x"))
    http = fake_http(response)
    with patch("utils.facebook_client.httpx.AsyncClient", return_value=http), patch(
        "utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: "token")
    ):
        c = FacebookClient(store())
        assert await c.mark_as_seen("u") == {"id": "post-1"}
        assert await c.publish_post("msg", image_url="https://img") == {"ok": True, "post_id": "post-1", "network": "facebook"}
        assert await c.publish_post("msg", link="https://link") == {"ok": True, "post_id": "post-1", "network": "facebook"}
    image_payload = http.post.await_args_list[1].kwargs["json"]
    assert image_payload["url"] == "https://img"
    link_payload = http.post.await_args_list[2].kwargs["json"]
    assert link_payload["link"] == "https://link"

@pytest.mark.asyncio
async def test_post_raises_http_error():
    response = httpx.Response(500, text="bad", request=httpx.Request("POST", "https://x"))
    http = fake_http(response)
    with patch("utils.facebook_client.httpx.AsyncClient", return_value=http), patch(
        "utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: "token")
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await FacebookClient(store()).send_text("u", "x")

@pytest.mark.asyncio
async def test_broadcast_counts_success_failure_and_caps_500():
    ok = httpx.Response(200, json={}, request=httpx.Request("POST", "https://x"))
    bad = httpx.Response(500, json={}, request=httpx.Request("POST", "https://x"))
    http = fake_http()
    http.post.side_effect = [ok, bad, RuntimeError("network")] + [ok] * 500
    with patch("utils.facebook_client.httpx.AsyncClient", return_value=http), patch(
        "utils.facebook_client.settings", SimpleNamespace(decrypt=lambda value: "token")
    ):
        result = await FacebookClient(store()).broadcast_messenger("hello", [str(i) for i in range(600)])
    assert result == {"ok": True, "sent": 498, "failed": 2, "network": "facebook"}
    assert http.post.await_count == 500
