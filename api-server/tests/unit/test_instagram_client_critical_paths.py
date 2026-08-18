from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from utils.instagram_client import InstagramClient


def store(token="enc", account="acct-1"):
    return SimpleNamespace(id=1, instagram_token_enc=token, instagram_account_id=account)


def make_http(response=None):
    http = AsyncMock()
    http.__aenter__.return_value = http
    if response is not None:
        http.post.return_value = response
    return http


def settings_patch(value="token"):
    return patch("utils.instagram_client.settings", SimpleNamespace(decrypt=lambda v: value))


def test_configuration_and_decrypt_failure():
    with settings_patch():
        c = InstagramClient(store())
    assert c.is_configured is True
    assert c.headers["Authorization"] == "Bearer token"
    with patch("utils.instagram_client.settings", SimpleNamespace(decrypt=lambda v: (_ for _ in ()).throw(RuntimeError("bad")))):
        assert InstagramClient(store()).is_configured is False
    assert InstagramClient(None).is_configured is False

@pytest.mark.asyncio
async def test_unconfigured_operations_return_errors():
    c = InstagramClient(None)
    assert await c.send_text("u", "x") == {"error": "not_configured"}
    assert await c.send_quick_replies("u", "x", []) == {"error": "not_configured"}
    assert await c.mark_as_seen("u") == {"error": "not_configured"}
    assert await c.publish_post("x", "img") == {"error": "instagram_not_configured"}
    assert await c.publish_story("img") == {"error": "instagram_not_configured"}

@pytest.mark.asyncio
async def test_send_text_product_card_and_quick_replies_payloads():
    response = httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", "https://x"))
    http = make_http(response)
    with settings_patch(), patch("utils.instagram_client.httpx.AsyncClient", return_value=http):
        c = InstagramClient(store())
        assert await c.send_text("u", "hello") == {"ok": True}
        await c.send_product_card("u", "shoe", 2.5, 4)
        await c.send_quick_replies("u", "choose", [str(i) for i in range(20)])
    product = http.post.await_args_list[1].kwargs["json"]["message"]["text"]
    assert "shoe" in product and "2.500" in product and "4 unité" in product
    quick = http.post.await_args_list[2].kwargs["json"]["message"]["quick_replies"]
    assert len(quick) == 13 and len(quick[0]["title"]) <= 20

@pytest.mark.asyncio
async def test_mark_seen_and_http_error_propagates():
    response = httpx.Response(200, json={"seen": True}, request=httpx.Request("POST", "https://x"))
    http = make_http(response)
    with settings_patch(), patch("utils.instagram_client.httpx.AsyncClient", return_value=http):
        assert await InstagramClient(store()).mark_as_seen("u") == {"seen": True}
    bad = httpx.Response(500, text="bad", request=httpx.Request("POST", "https://x"))
    http = make_http(bad)
    with settings_patch(), patch("utils.instagram_client.httpx.AsyncClient", return_value=http):
        with pytest.raises(httpx.HTTPStatusError):
            await InstagramClient(store()).send_text("u", "x")

@pytest.mark.asyncio
async def test_publish_post_two_steps_and_missing_container():
    create = httpx.Response(200, json={"id": "container"}, request=httpx.Request("POST", "https://x"))
    publish = httpx.Response(200, json={"id": "post"}, request=httpx.Request("POST", "https://x"))
    http = make_http()
    http.post.side_effect = [create, publish]
    with settings_patch(), patch("utils.instagram_client.httpx.AsyncClient", return_value=http):
        result = await InstagramClient(store()).publish_post("caption", "https://img")
    assert result == {"ok": True, "post_id": "post", "network": "instagram"}
    assert http.post.await_args_list[0].kwargs["json"]["image_url"] == "https://img"
    assert http.post.await_args_list[1].kwargs["json"] ["creation_id"] == "container"
    http = make_http(httpx.Response(200, json={}, request=httpx.Request("POST", "https://x")))
    with settings_patch(), patch("utils.instagram_client.httpx.AsyncClient", return_value=http):
        assert await InstagramClient(store()).publish_post("caption", "img") == {"error": "container_creation_failed"}

@pytest.mark.asyncio
async def test_publish_story_two_steps():
    create = httpx.Response(200, json={"id": "story-container"}, request=httpx.Request("POST", "https://x"))
    publish = httpx.Response(200, json={"id": "story"}, request=httpx.Request("POST", "https://x"))
    http = make_http()
    http.post.side_effect = [create, publish]
    with settings_patch(), patch("utils.instagram_client.httpx.AsyncClient", return_value=http):
        result = await InstagramClient(store()).publish_story("https://img")
    assert result == {"ok": True, "story_id": "story", "network": "instagram"}
    assert http.post.await_args_list[0].kwargs["json"]["media_type"] == "STORIES"
