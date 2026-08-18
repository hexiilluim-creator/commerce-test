from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from utils.tiktok_client import TikTokClient


def store(token="enc", open_id="open-1"):
    return SimpleNamespace(id=1, tiktok_token_enc=token, tiktok_open_id=open_id)


def settings_obj(enabled=True, real=False, env="test"):
    return SimpleNamespace(
        decrypt=lambda value: "token",
        TIKTOK_ENABLED=enabled,
        TIKTOK_ALLOW_REAL_CALLS=real,
        ENV=env,
    )


def test_configuration_real_calls_and_decrypt_failure():
    with patch("utils.tiktok_client.settings", settings_obj()):
        c = TikTokClient(store())
    assert c.is_configured is True
    assert c.real_calls_enabled is False
    with patch("utils.tiktok_client.settings", SimpleNamespace(decrypt=lambda v: (_ for _ in ()).throw(RuntimeError("bad")), TIKTOK_ENABLED=True, TIKTOK_ALLOW_REAL_CALLS=False, ENV="test")):
        assert TikTokClient(store()).is_configured is False
    assert TikTokClient(None).is_configured is False

@pytest.mark.asyncio
async def test_unconfigured_operations_return_errors():
    with patch("utils.tiktok_client.settings", settings_obj()):
        c = TikTokClient(None)
        assert await c.send_text("u", "x") == {"error": "not_configured"}
        assert await c.send_image("u", "img") == {"error": "not_configured"}
        assert await c.publish_video("url", "caption") == {"error": "tiktok_not_configured"}
        assert await c.publish_photo(["img"], "caption") == {"error": "tiktok_not_configured"}

@pytest.mark.asyncio
async def test_disabled_post_returns_dry_run_payload():
    with patch("utils.tiktok_client.settings", settings_obj(enabled=False)):
        result = await TikTokClient(store()).send_text("u", "hello")
    assert result["status"] == "disabled"
    assert result["dry_run"] is True
    assert result["payload"]["content"] == {"text": "hello"}

@pytest.mark.asyncio
async def test_nonproduction_post_returns_dry_run_without_http():
    with patch("utils.tiktok_client.settings", settings_obj(enabled=True, real=True, env="test")), patch(
        "utils.tiktok_client.httpx.AsyncClient"
    ) as http:
        result = await TikTokClient(store()).send_image("u", "img")
    assert result["status"] == "dry_run"
    http.assert_not_called()

@pytest.mark.asyncio
async def test_send_text_and_product_card_send_payloads_in_dry_run():
    with patch("utils.tiktok_client.settings", settings_obj()):
        c = TikTokClient(store())
        text = await c.send_text("u", "hello")
        card = await c.send_product_card("u", "shoe", 2.5, 4, "img")
    assert text["payload"]["message_type"] == "TEXT"
    assert "shoe" in card["payload"]["content"]["text"]

@pytest.mark.asyncio
async def test_real_post_success_and_api_error_payload():
    ok = httpx.Response(200, json={"code": 0, "message": "ok"}, request=httpx.Request("POST", "https://x"))
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.post.return_value = ok
    real_settings = settings_obj(enabled=True, real=True, env="production")
    with patch("utils.tiktok_client.settings", real_settings), patch("utils.tiktok_client.os.getenv", return_value=None), patch("utils.tiktok_client.httpx.AsyncClient", return_value=http):
        result = await TikTokClient(store()).send_text("u", "hello")
    assert result == {"code": 0, "message": "ok"}
    assert http.post.await_args.kwargs["json"]["to_user_open_id"] == "u"

@pytest.mark.asyncio
async def test_real_post_http_error_propagates():
    response = httpx.Response(500, text="bad", request=httpx.Request("POST", "https://x"))
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.post.return_value = response
    with patch("utils.tiktok_client.settings", settings_obj(enabled=True, real=True, env="production")), patch("utils.tiktok_client.os.getenv", return_value=None), patch(
        "utils.tiktok_client.httpx.AsyncClient", return_value=http
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await TikTokClient(store()).send_text("u", "x")

@pytest.mark.asyncio
async def test_product_card_image_failure_is_noncritical():
    with patch("utils.tiktok_client.settings", settings_obj()), patch.object(
        TikTokClient, "send_text", new=AsyncMock(return_value={"ok": True})
    ), patch.object(TikTokClient, "send_image", new=AsyncMock(side_effect=RuntimeError("image"))):
        result = await TikTokClient(store()).send_product_card("u", "shoe", 1, 1, "img")
    assert result == {"ok": True}

@pytest.mark.asyncio
async def test_publish_video_and_photo_payload_limits():
    video_resp = httpx.Response(200, json={"data": {"publish_id": "vid"}}, request=httpx.Request("POST", "https://x"))
    photo_resp = httpx.Response(200, json={"data": {"publish_id": "photo"}}, request=httpx.Request("POST", "https://x"))
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.post.side_effect = [video_resp, photo_resp]
    with patch("utils.tiktok_client.settings", settings_obj()), patch("utils.tiktok_client.httpx.AsyncClient", return_value=http):
        c = TikTokClient(store())
        assert await c.publish_video("video", "a" * 200) == {"ok": True, "publish_id": "vid", "network": "tiktok"}
        assert await c.publish_photo([str(i) for i in range(40)], "caption") == {"ok": True, "publish_id": "photo", "network": "tiktok"}
    video_json = http.post.await_args_list[0].kwargs["json"]
    assert len(video_json["post_info"]["title"]) == 150
    photo_json = http.post.await_args_list[1].kwargs["json"]
    assert len(photo_json["source_info"]["photo_images"]) == 35
