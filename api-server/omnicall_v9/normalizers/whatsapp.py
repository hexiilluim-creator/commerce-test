"""Pure WhatsApp -> UnifiedMessage normalization."""

from __future__ import annotations

from omnicall_v9.normalizers.common import (
    build_identity,
    build_interactive,
    build_location,
    build_media_list,
    ensure_message_id,
    normalize_message_kind,
    parse_event_at,
)
from omnicall_v9.types.unified_message import ChannelType, DirectionType, UnifiedMessage


def normalize_whatsapp_payload(payload: dict[str, object]) -> UnifiedMessage:
    """Normalize the current WhatsApp internal payload built by api/v1/whatsapp.py.

    Expected shape mirrors the existing webhook handler output, for example:
    {
        "from": "+21611111111",
        "id": "wamid.123",
        "type": "text",
        "body": "Bonjour",
        "store_id": 1,
        "phone_number_id": "1234567890"
    }
    """
    sender = build_identity({"phone": payload.get("from")})
    recipient = None
    if payload.get("phone_number_id"):
        recipient = build_identity({"external_id": payload.get("phone_number_id")})

    external_message_id = payload.get("id") or payload.get("message_id")
    kind = normalize_message_kind(payload.get("type"))

    return UnifiedMessage(
        message_id=ensure_message_id(
            channel=ChannelType.WHATSAPP.value,
            external_message_id=external_message_id,
            sender_hint=payload.get("from"),
        ),
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=kind,
        event_at=parse_event_at(payload.get("timestamp") or payload.get("event_at")),
        store_id=payload.get("store_id"),
        tenant_ref=payload.get("tenant_ref"),
        channel_account_id=payload.get("phone_number_id"),
        channel_message_id=external_message_id,
        sender=sender,
        recipient=recipient,
        text=payload.get("body") or payload.get("text"),
        media=build_media_list(payload),
        location=build_location(payload),
        interactive=build_interactive(payload),
        raw_event=dict(payload),
        trace_id=payload.get("trace_id"),
        metadata=payload.get("metadata") or {},
    )
