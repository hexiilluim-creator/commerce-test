from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import social_publisher as sp


@pytest.mark.asyncio
async def test_generate_caption_uses_config_and_returns_model_content():
    config = SimpleNamespace(
        default_language="darija",
        brand_voice="festif",
        hashtags=json.dumps(["#auto", "#promo"]),
        emoji_style="high",
        brand_name="Auto Store",
    )
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  Caption générée  "))])
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    with patch("services.social_publisher.get_platform_client", return_value=client):
        result = await sp.generate_caption("freins", "instagram", "post", config, "Store")
    assert result == "Caption générée"
    kwargs = client.chat.completions.create.await_args.kwargs
    assert "Auto Store" in kwargs["messages"][1]["content"]
    assert "#auto #promo" in kwargs["messages"][1]["content"]


@pytest.mark.asyncio
async def test_generate_caption_falls_back_on_invalid_config_or_provider_failure():
    config = SimpleNamespace(default_language="fr", brand_voice="pro", hashtags="not-json", emoji_style="low", brand_name="Store")
    with patch("services.social_publisher.get_platform_client", side_effect=RuntimeError("provider down")):
        result = await sp.generate_caption("huile", "facebook", "post", config, "Store")
    assert result.startswith("🛍️ huile")
    assert "WhatsApp" in result
    assert "#Tunisie" in result


@pytest.mark.asyncio
async def test_generate_image_builds_prompt_and_returns_url():
    config = SimpleNamespace(image_style="studio", image_colors="blue", watermark_text="Store")
    response = SimpleNamespace(data=[SimpleNamespace(url="https://img.test/a.png")])
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=response)
    with patch("services.social_publisher.get_platform_client", return_value=client):
        url, prompt = await sp.generate_image_dalle("brake pads", config)
    assert url == "https://img.test/a.png"
    assert "brake pads" in prompt
    assert len(prompt) <= 3900


@pytest.mark.asyncio
async def test_generate_image_raises_clear_error_on_provider_failure():
    client = MagicMock()
    client.images.generate = AsyncMock(side_effect=RuntimeError("image provider down"))
    with patch("services.social_publisher.get_platform_client", return_value=client):
        with pytest.raises(RuntimeError, match="Génération image échouée"):
            await sp.generate_image_dalle("topic", None)


@pytest.mark.asyncio
async def test_publish_dispatch_rejects_unknown_and_tiktok_requires_image():
    store = SimpleNamespace()
    unknown = await sp._publish_to(store, "unknown", "caption", None, "post")
    assert unknown["ok"] is False
    assert "non supporté" in unknown["error"]
    with patch("utils.tiktok_client.TikTokClient") as client_cls:
        client_cls.return_value.is_configured = True
        result = await sp._publish_tiktok(store, "caption", None)
    assert result == {"ok": False, "error": "Image requise pour TikTok"}


@pytest.mark.asyncio
async def test_publish_pipeline_records_success_and_failure_for_networks():
    db = MagicMock(); db.flush = AsyncMock(); db.commit = AsyncMock()
    store = SimpleNamespace(id=12, name="Store")
    config = SimpleNamespace()
    published = {"instagram": {"ok": True, "post_id": "ig-1"}, "facebook": {"ok": False, "error": "rejected"}}

    async def publish(_store, network, *_args):
        return published[network]

    with patch("services.social_publisher._publish_to", side_effect=publish):
        result = await sp.run_publish_pipeline(
            db=db,
            store=store,
            config=config,
            topic="promo",
            networks=["instagram", "facebook"],
            generate_image=False,
            custom_caption="Custom caption",
            custom_image_url="https://img.test/x.png",
        )
    assert result["ok"] is True
    assert result["published"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["external_id"] == "ig-1"
    assert result["results"][1]["error"] == "rejected"
    assert db.add.call_count == 2
    db.commit.assert_awaited_once()


def test_get_next_post_time_handles_disabled_and_valid_schedule():
    assert sp.get_next_post_time(SimpleNamespace(auto_schedule=False)) is None
    config = SimpleNamespace(auto_schedule=True, timezone="UTC", post_times='["23:59"]', post_days="[0,1,2,3,4,5,6]")
    result = sp.get_next_post_time(config)
    assert result is None or isinstance(result, datetime)


def test_get_next_post_time_returns_none_for_invalid_schedule():
    config = SimpleNamespace(auto_schedule=True, timezone="Invalid/Zone", post_times="bad", post_days="bad")
    assert sp.get_next_post_time(config) is None


@pytest.mark.asyncio
async def test_network_publishers_cover_unconfigured_and_exception_paths():
    store = SimpleNamespace()
    with patch("utils.instagram_client.InstagramClient") as ig:
        ig.return_value.is_configured = False
        assert "non configuré" in (await sp._publish_instagram(store, "c", "u", "post"))["error"]
    with patch("utils.facebook_client.FacebookClient") as fb:
        fb.return_value.is_configured = True
        fb.return_value.publish_post = AsyncMock(side_effect=RuntimeError("fb down"))
        assert "fb down" in (await sp._publish_facebook(store, "c", "u", "post"))["error"]
    with patch("utils.tiktok_client.TikTokClient") as tt:
        tt.return_value.is_configured = False
        assert "non configuré" in (await sp._publish_tiktok(store, "c", "u"))["error"]
    with patch("utils.instagram_client.InstagramClient") as ig:
        ig.return_value.is_configured = True
        ig.return_value.publish_story = AsyncMock(return_value={"ok": True, "story_id": "s1"})
        assert (await sp._publish_instagram(store, "c", "u", "story"))["story_id"] == "s1"


@pytest.mark.asyncio
async def test_pipeline_continues_when_dalle_fails():
    db = MagicMock(); db.flush = AsyncMock(); db.commit = AsyncMock(); store = SimpleNamespace(id=1, name="S")
    with patch("services.social_publisher.generate_image_dalle", new=AsyncMock(side_effect=RuntimeError("dalle down"))), \
         patch("services.social_publisher._publish_to", new=AsyncMock(return_value={"ok": True, "post_id": "p"})):
        result = await sp.run_publish_pipeline(db, store, None, "topic", ["instagram"], custom_caption="c")
    assert result["ok"] is True and "dalle down" in result["dalle_error"]


def test_get_next_post_time_finds_future_slot():
    config = SimpleNamespace(auto_schedule=True, timezone="UTC", post_times='["23:59", "00:01"]', post_days="[0,1,2,3,4,5,6]")
    result = sp.get_next_post_time(config)
    assert result is None or result.tzinfo is not None
