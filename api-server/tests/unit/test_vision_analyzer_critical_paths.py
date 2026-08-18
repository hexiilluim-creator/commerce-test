from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services import vision_analyzer as va


def response_with(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_guess_media_types_and_default():
    assert va._guess_media_type(b"\xff\xd8\xffrest") == "image/jpeg"
    assert va._guess_media_type(b"\x89PNGrest") == "image/png"
    assert va._guess_media_type(b"RIFFxxxxWEBPdata") == "image/webp"
    assert va._guess_media_type(b"GIF89adata") == "image/gif"
    assert va._guess_media_type(b"unknown") == "image/jpeg"


def test_extract_clean_and_coerce_payload():
    assert va._extract_text_content(response_with("  hi  ")) == "hi"
    assert va._extract_text_content(SimpleNamespace()) == ""
    assert va._clean_json_payload("```json\n{\"name\": \"x\"}\n```") == '{"name": "x"}'
    assert va._clean_json_payload("  {} ") == "{}"
    result = va._coerce_result({"name": " Lamp ", "price_hint": "12.5", "tags": ["new", "", 2]})
    assert result == {"name": " Lamp ", "description": "", "category": "other", "price_hint": 12.5, "tags": ["new", "2"]}
    assert va._coerce_result({"price_hint": "bad", "tags": "bad"})["price_hint"] is None
    assert va._coerce_result([]) == va.DEFAULT_VISION_RESULT


@pytest.mark.asyncio
async def test_analyze_image_bytes_valid_json_and_media_payload():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response_with('{"name":"shoe","tags":["sale"]}')))))
    with patch("services.vision_analyzer.get_platform_client", return_value=client):
        result = await va.analyze_image_bytes(b"\x89PNGdata")
    assert result["name"] == "shoe"
    assert result["tags"] == ["sale"]
    kwargs = client.chat.completions.create.await_args.kwargs
    assert "image_url" in str(kwargs["messages"])
    assert "image/png" in str(kwargs["messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not-json", "```json\nnot-json\n```"])
async def test_analyze_image_bytes_invalid_json_returns_default(raw):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response_with(raw)))))
    with patch("services.vision_analyzer.get_platform_client", return_value=client):
        result = await va.analyze_image_bytes(b"data")
    assert result == va.DEFAULT_VISION_RESULT


@pytest.mark.asyncio
async def test_analyze_image_bytes_handles_timeout_and_provider_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=TimeoutError()))))
    with patch("services.vision_analyzer.get_platform_client", return_value=client):
        assert await va.analyze_image_bytes(b"data") == va.DEFAULT_VISION_RESULT
    client.chat.completions.create.side_effect = RuntimeError("provider down")
    with patch("services.vision_analyzer.get_platform_client", return_value=client):
        assert await va.analyze_image_bytes(b"data") == va.DEFAULT_VISION_RESULT


@pytest.mark.asyncio
async def test_analyze_image_base64_returns_raw_text():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response_with("OCR text")))))
    with patch("services.vision_analyzer.resolve_openai_client", new=AsyncMock(return_value=client)):
        result = await va.analyze_image_base64("YWJj", "image/png", "read", 1, object())
    assert result == "OCR text"


@pytest.mark.asyncio
async def test_analyze_image_url_downloads_and_delegates():
    response = httpx.Response(200, content=b"image-bytes", request=httpx.Request("GET", "https://example.test/a.png"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = response
    with patch("services.vision_analyzer.httpx.AsyncClient", return_value=client), patch(
        "services.vision_analyzer.analyze_image_bytes", new=AsyncMock(return_value={"name": "x"})
    ) as analyze:
        result = await va.analyze_image_url("https://example.test/a.png")
    assert result == {"name": "x"}
    analyze.assert_awaited_once_with(b"image-bytes", store_id=None, db=None)


@pytest.mark.asyncio
async def test_analyze_whatsapp_image_handles_missing_media_and_success():
    with patch("services.voice_transcriber._download_media", new=AsyncMock(return_value=None)):
        result = await va.analyze_whatsapp_image("media", None)
    assert result["found"] is False
    store = SimpleNamespace(id=7)
    with patch("services.voice_transcriber._download_media", new=AsyncMock(return_value=b"bytes")), patch(
        "services.vision_analyzer.analyze_image_bytes", new=AsyncMock(return_value={"name": "x"})
    ) as analyze:
        result = await va.analyze_whatsapp_image("media", store, object())
    assert result == {"name": "x"}
    analyze.assert_awaited_once_with(b"bytes", store_id=7, db=analyze.call_args.kwargs["db"])
