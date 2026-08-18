"""Pure Instagram -> UnifiedMessage normalization."""

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


def normalize_instagram_payload(payload: dict[str, object]) -> UnifiedMessage:
    sender_payload = payload.get("sender") or {}
    recipient_payload = payload.get("recipient") or {}
    external_message_id = payload.get("message_id") or payload.get("id")

    sender = build_identity(
        sender_payload,
        external_id=payload.get("sender_id"),
        username=payload.get("username"),
        display_name=payload.get("display_name"),
    )
    recipient = None
    if recipient_payload or payload.get("recipient_id"):
        recipient = build_identity(recipient_payload, external_id=payload.get("recipient_id"))

    kind = normalize_message_kind(payload.get("type") or payload.get("message_kind") or ("image" if payload.get("attachments") else "text"))

    return UnifiedMessage(
        message_id=ensure_message_id(
            channel=ChannelType.INSTAGRAM.value,
            external_message_id=external_message_id,
            sender_hint=sender.external_id or sender.username,
        ),
        channel=ChannelType.INSTAGRAM,
        direction=DirectionType.INBOUND,
        message_kind=kind,
        event_at=parse_event_at(payload.get("timestamp") or payload.get("event_at")),
        store_id=payload.get("store_id"),
        tenant_ref=payload.get("tenant_ref"),
        channel_account_id=payload.get("instagram_account_id") or payload.get("recipient_id"),
        channel_message_id=external_message_id,
        sender=sender,
        recipient=recipient,
        text=payload.get("text") or payload.get("body"),
        media=build_media_list(payload),
        location=build_location(payload),
        interactive=build_interactive(payload),
        raw_event=dict(payload),
        trace_id=payload.get("trace_id"),
        metadata=payload.get("metadata") or {},
    )
