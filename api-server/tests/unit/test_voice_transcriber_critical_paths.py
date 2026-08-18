from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services import voice_transcriber as vt


def test_language_detection_heuristics():
    assert vt.detect_language_hint("") is None
    assert vt.detect_language_hint("مرحبا كيف حالك") == "ar"
    assert vt.detect_language_hint("bonjour merci pour le produit") == "fr"
    assert vt.detect_language_hint("hello product") is None

@pytest.mark.asyncio
async def test_cache_helpers_fail_safe_on_redis_errors():
    with patch.dict("os.environ", {"REDIS_URL": "redis://invalid:1"}):
        assert await vt._cache_get("x") is None
        assert await vt._cache_set("x", "value") is None

@pytest.mark.asyncio
async def test_get_access_token_prefers_store_then_env_and_falls_back_on_decrypt_error(monkeypatch):
    store = SimpleNamespace(whatsapp_access_token_enc="enc")
    fake_settings = SimpleNamespace(decrypt=lambda value: "decrypted")
    with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": "global"}), patch("config.settings", fake_settings):
        assert await vt._get_wa_access_token(store) == "decrypted"
    with patch.dict("os.environ", {"WHATSAPP_ACCESS_TOKEN": "global"}), patch(
        "config.settings", SimpleNamespace(decrypt=lambda value: (_ for _ in ()).throw(RuntimeError("bad")))
    ):
        assert await vt._get_wa_access_token(store) == "global"
    assert await vt._get_wa_access_token(SimpleNamespace(whatsapp_access_token_enc=None)) is not None

@pytest.mark.asyncio
async def test_download_media_performs_metadata_then_binary_request():
    meta = httpx.Response(200, json={"url": "https://cdn.test/media"}, request=httpx.Request("GET", "https://graph.test"))
    binary = httpx.Response(200, content=b"audio", headers={"content-type": "audio/ogg"}, request=httpx.Request("GET", "https://cdn.test/media"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = [meta, binary]
    with patch("services.voice_transcriber.httpx.AsyncClient", return_value=client), patch.dict(
        "os.environ", {"WHATSAPP_ACCESS_TOKEN": "token"}
    ):
        result = await vt._download_media("media-1")
    assert result == b"audio"
    assert client.get.await_count == 2

@pytest.mark.asyncio
async def test_download_media_rejects_missing_url():
    meta = httpx.Response(200, json={}, request=httpx.Request("GET", "https://graph.test"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = meta
    with patch("services.voice_transcriber.httpx.AsyncClient", return_value=client):
        with pytest.raises(ValueError, match="No download URL"):
            await vt._download_media("media-2")

@pytest.mark.asyncio
async def test_transcribe_bytes_returns_empty_without_key_and_cleans_temp(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert await vt._transcribe_bytes(b"audio") == ""

@pytest.mark.asyncio
async def test_transcribe_bytes_posts_file_and_language_and_returns_text():
    resp = httpx.Response(200, json={"text": " bonjour "}, request=httpx.Request("POST", vt._WHISPER_URL))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = resp
    with patch.dict("os.environ", {"OPENAI_API_KEY": "key"}), patch(
        "services.voice_transcriber.httpx.AsyncClient", return_value=client
    ):
        result = await vt._transcribe_bytes(b"audio", "audio/ogg", "fr")
    assert result == "bonjour"
    kwargs = client.post.await_args.kwargs
    assert kwargs["data"]["language"] == "fr"
    assert kwargs["data"]["model"] == "whisper-1"

@pytest.mark.asyncio
async def test_transcribe_bytes_returns_empty_on_http_or_generic_error():
    request = httpx.Request("POST", vt._WHISPER_URL)
    error_response = httpx.Response(500, request=request)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = error_response
    with patch.dict("os.environ", {"OPENAI_API_KEY": "key"}), patch(
        "services.voice_transcriber.httpx.AsyncClient", return_value=client
    ):
        assert await vt._transcribe_bytes(b"audio") == ""
    client.post.side_effect = RuntimeError("down")
    with patch.dict("os.environ", {"OPENAI_API_KEY": "key"}), patch(
        "services.voice_transcriber.httpx.AsyncClient", return_value=client
    ):
        assert await vt._transcribe_bytes(b"audio") == ""

@pytest.mark.asyncio
async def test_transcribe_whatsapp_uses_cache_and_skips_network():
    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value="cached")), patch(
        "services.voice_transcriber._download_media", new=AsyncMock()
    ) as download:
        assert await vt.transcribe_whatsapp_audio("media") == "cached"
    download.assert_not_awaited()

@pytest.mark.asyncio
async def test_transcribe_whatsapp_download_failure_and_empty_media_return_empty():
    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value=None)), patch(
        "services.voice_transcriber._download_media", new=AsyncMock(side_effect=RuntimeError("down"))
    ):
        assert await vt.transcribe_whatsapp_audio("media") == ""
    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value=None)), patch(
        "services.voice_transcriber._download_media", new=AsyncMock(return_value=b"")
    ):
        assert await vt.transcribe_whatsapp_audio("media") == ""

@pytest.mark.asyncio
async def test_transcribe_whatsapp_transcribes_and_caches_nonempty_text():
    with patch("services.voice_transcriber._cache_get", new=AsyncMock(return_value=None)), patch(
        "services.voice_transcriber._download_media", new=AsyncMock(return_value=b"audio")
    ), patch("services.voice_transcriber._transcribe_bytes", new=AsyncMock(return_value="hello")), patch(
        "services.voice_transcriber._cache_set", new=AsyncMock()
    ) as cache_set:
        assert await vt.transcribe_whatsapp_audio("media", mime_type="audio/mpeg", language_hint="fr") == "hello"
    cache_set.assert_awaited_once_with("whisper:transcript:media", "hello")
