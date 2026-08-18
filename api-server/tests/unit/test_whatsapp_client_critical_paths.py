from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from utils.whatsapp_client import WhatsAppClient


def make_http(response):
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.post.return_value = response
    return http


def test_configuration_and_factories():
    assert WhatsAppClient(None, None).is_configured is False
    with patch("config.settings.WHATSAPP_PHONE_NUMBER_ID", "phone"), patch("config.settings.WHATSAPP_ACCESS_TOKEN", "token"):
        c = WhatsAppClient.from_settings()
    assert c.is_configured is True
    assert c._headers["Authorization"] == "Bearer token"


def test_from_store_prefers_decrypted_byok_and_falls_back_global():
    store = SimpleNamespace(id=1, whatsapp_access_token_enc="enc", whatsapp_phone_number_id="store-phone")
    fake = SimpleNamespace(
        decrypt=lambda value: "byok-token",
        WHATSAPP_ACCESS_TOKEN="global-token",
        WHATSAPP_PHONE_NUMBER_ID="global-phone",
    )
    with patch("config.settings", fake):
        c = WhatsAppClient.from_store(store)
    assert c.phone_number_id == "store-phone"
    assert c.access_token == "byok-token"
    fake.decrypt = lambda value: (_ for _ in ()).throw(RuntimeError("bad"))
    with patch("config.settings", fake):
        c = WhatsAppClient.from_store(SimpleNamespace(id=1, whatsapp_access_token_enc="bad", whatsapp_phone_number_id=None))
    assert c.phone_number_id == "global-phone"
    assert c.access_token == "global-token"

@pytest.mark.asyncio
async def test_all_payload_methods_delegate_to_post():
    response = httpx.Response(200, json={"messages": [{"id": "m"}]}, request=httpx.Request("POST", "https://x"))
    http = make_http(response)
    with patch("utils.whatsapp_client.httpx.AsyncClient", return_value=http):
        c = WhatsAppClient("phone", "token")
        await c.send_text("u", "hello")
        await c.send_template("u", "welcome", components=[{"type": "body"}])
        await c.send_interactive_list("u", "body", "choose", [{"rows": []}])
        await c.send_list_message("u", "body", [], button="go")
        await c.send_interactive_buttons("u", "body", [{"type": "reply"}])
        await c.send_image("u", "img", caption="cap")
        await c.mark_as_read("m")
    assert http.post.await_count == 7
    assert http.post.await_args_list[0].kwargs["json"]["type"] == "text"
    assert http.post.await_args_list[1].kwargs["json"]["template"]["name"] == "welcome"
    assert http.post.await_args_list[2].kwargs["json"]["interactive"]["type"] == "list"
    assert http.post.await_args_list[4].kwargs["json"]["interactive"]["type"] == "button"
    assert http.post.await_args_list[5].kwargs["json"]["image"]["caption"] == "cap"
    assert http.post.await_args_list[6].kwargs["json"]["status"] == "read"

@pytest.mark.asyncio
async def test_image_omits_empty_caption_and_unconfigured_raises():
    response = httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", "https://x"))
    http = make_http(response)
    with patch("utils.whatsapp_client.httpx.AsyncClient", return_value=http):
        await WhatsAppClient("phone", "token").send_image("u", "img", caption="")
    assert "caption" not in http.post.await_args.kwargs["json"]["image"]
    with pytest.raises(RuntimeError, match="not configured"):
        await WhatsAppClient(None, None).send_text("u", "x")

@pytest.mark.asyncio
async def test_http_status_and_transport_errors_propagate():
    bad = httpx.Response(500, text="bad", request=httpx.Request("POST", "https://x"))
    http = make_http(bad)
    with patch("utils.whatsapp_client.httpx.AsyncClient", return_value=http):
        with pytest.raises(httpx.HTTPStatusError):
            await WhatsAppClient("phone", "token").send_text("u", "x")
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.post.side_effect = RuntimeError("network")
    with patch("utils.whatsapp_client.httpx.AsyncClient", return_value=http):
        with pytest.raises(RuntimeError, match="network"):
            await WhatsAppClient("phone", "token").send_text("u", "x")
