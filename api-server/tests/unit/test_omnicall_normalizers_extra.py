from __future__ import annotations

from datetime import UTC, datetime

from omnicall_v9.normalizers.common import (
    build_identity,
    build_interactive,
    build_location,
    build_media_list,
    ensure_message_id,
    normalize_message_kind,
    parse_event_at,
)
from omnicall_v9.normalizers.facebook import normalize_facebook_payload
from omnicall_v9.normalizers.instagram import normalize_instagram_payload
from omnicall_v9.normalizers.tiktok import normalize_tiktok_payload
from omnicall_v9.normalizers.whatsapp import normalize_whatsapp_payload
from omnicall_v9.types.unified_message import ChannelType, InteractiveReplyType, MessageKind


def test_normalize_message_kind_and_parse_event_at_cover_common_inputs() -> None:
    assert normalize_message_kind(" IMAGE ") is MessageKind.IMAGE
    assert normalize_message_kind(None) is MessageKind.UNKNOWN
    assert parse_event_at("2026-07-15T10:30:00Z") == datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
    assert parse_event_at(1_751_000_000).tzinfo is UTC



def test_build_identity_media_location_and_interactive_helpers() -> None:
    identity = build_identity({"id": "user-1", "handle": "garage", "name": "Garage One"})
    media = build_media_list(
        {
            "attachments": [
                {"id": "m1", "mime_type": "image/jpeg", "url": "https://cdn.test/image.jpg", "caption": "Produit"}
            ]
        }
    )
    location = build_location({"latitude": 36.8, "longitude": 10.1, "location_name": "Tunis"})
    interactive = build_interactive({"button_id": "cta-buy", "button_title": "Acheter"})

    assert identity.external_id == "user-1"
    assert identity.username == "garage"
    assert identity.display_name == "Garage One"
    assert len(media) == 1
    assert media[0].media_id == "m1"
    assert media[0].caption == "Produit"
    assert location is not None
    assert location.name == "Tunis"
    assert interactive is not None
    assert interactive.reply_type is InteractiveReplyType.BUTTON
    assert interactive.reply_id == "cta-buy"



def test_ensure_message_id_falls_back_to_fingerprint_when_missing() -> None:
    generated = ensure_message_id(channel="whatsapp", external_message_id="  ", sender_hint="+21600112233")

    assert generated.startswith("wha-")
    assert len(generated) == 36



def test_normalize_whatsapp_payload_builds_media_and_recipient() -> None:
    message = normalize_whatsapp_payload(
        {
            "from": "+21611111111",
            "id": "wamid.123",
            "type": "image",
            "timestamp": "2026-07-15T11:00:00Z",
            "store_id": 7,
            "phone_number_id": "acct-55",
            "caption": "Promo",
            "media_url": "https://cdn.test/promo.jpg",
        }
    )

    assert message.channel is ChannelType.WHATSAPP
    assert message.message_kind is MessageKind.IMAGE
    assert message.channel_message_id == "wamid.123"
    assert message.sender.phone == "+21611111111"
    assert message.recipient is not None
    assert message.recipient.external_id == "acct-55"
    assert message.media[0].url == "https://cdn.test/promo.jpg"



def test_normalize_facebook_payload_detects_interactive_messages() -> None:
    message = normalize_facebook_payload(
        {
            "mid": "fb-mid-1",
            "sender": {"id": "psid-1", "name": "Client FB"},
            "recipient": {"id": "page-9"},
            "page_id": "page-9",
            "interactive": {"type": "button", "id": "btn-1", "title": "Commander"},
            "timestamp": 1_751_000_100,
        }
    )

    assert message.channel is ChannelType.FACEBOOK
    assert message.message_kind is MessageKind.INTERACTIVE
    assert message.sender.external_id == "psid-1"
    assert message.recipient is not None
    assert message.recipient.external_id == "page-9"
    assert message.interactive is not None
    assert message.interactive.reply_id == "btn-1"



def test_normalize_instagram_payload_infers_image_kind_from_attachments() -> None:
    message = normalize_instagram_payload(
        {
            "sender_id": "ig-user-1",
            "recipient_id": "ig-biz-9",
            "attachments": [{"id": "att-1", "url": "https://cdn.test/story.jpg"}],
            "text": "story",
            "timestamp": "1751000200",
        }
    )

    assert message.channel is ChannelType.INSTAGRAM
    assert message.message_kind is MessageKind.IMAGE
    assert message.sender.external_id == "ig-user-1"
    assert message.recipient is not None
    assert message.recipient.external_id == "ig-biz-9"
    assert message.media[0].url == "https://cdn.test/story.jpg"



def test_normalize_tiktok_payload_infers_video_kind_and_keeps_metadata() -> None:
    message = normalize_tiktok_payload(
        {
            "open_id": "tt-user-1",
            "business_account_id": "tt-biz-7",
            "attachments": [{"id": "vid-9", "url": "https://cdn.test/video.mp4", "mime_type": "video/mp4"}],
            "metadata": {"campaign": "summer"},
            "trace_id": "trace-99",
        }
    )

    assert message.channel is ChannelType.TIKTOK
    assert message.message_kind is MessageKind.VIDEO
    assert message.sender.external_id == "tt-user-1"
    assert message.channel_account_id == "tt-biz-7"
    assert message.trace_id == "trace-99"
    assert message.metadata == {"campaign": "summer"}
    assert message.media[0].mime_type == "video/mp4"
