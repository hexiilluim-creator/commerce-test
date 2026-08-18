"""Pure helpers for OmniCall V9 payload normalization.

These helpers must stay side-effect free:
- no DB access
- no network
- no AI calls
"""

from __future__ import annotations

from datetime import UTC, datetime

from omnicall_v9.types.unified_message import (
    IdentityRef,
    InteractivePayload,
    InteractiveReplyType,
    LocationPayload,
    MediaAttachment,
    MessageKind,
)
from omnicall_v9.utils.ids import build_message_fingerprint

_KIND_MAP: dict[str, MessageKind] = {
    "text": MessageKind.TEXT,
    "image": MessageKind.IMAGE,
    "audio": MessageKind.AUDIO,
    "video": MessageKind.VIDEO,
    "document": MessageKind.DOCUMENT,
    "interactive": MessageKind.INTERACTIVE,
    "location": MessageKind.LOCATION,
    "status": MessageKind.STATUS,
}


def normalize_message_kind(value: str | None) -> MessageKind:
    if not value:
        return MessageKind.UNKNOWN
    return _KIND_MAP.get(str(value).strip().lower(), MessageKind.UNKNOWN)


def parse_event_at(value: str | int | float | datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return datetime.now(UTC)
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw), tz=UTC)
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    raise ValueError("Unsupported timestamp format")


def build_identity(payload: dict[str, object] | None = None, **fallbacks: object) -> IdentityRef:
    data = dict(payload or {})
    for key, value in fallbacks.items():
        data.setdefault(key, value)
    return IdentityRef(
        external_id=data.get("external_id") or data.get("id") or data.get("sender_id") or data.get("recipient_id"),
        phone=data.get("phone"),
        username=data.get("username") or data.get("handle"),
        display_name=data.get("display_name") or data.get("name"),
    )


def build_media_list(payload: dict[str, object]) -> list[MediaAttachment]:
    attachments = payload.get("attachments")
    if isinstance(attachments, list) and attachments:
        return [
            MediaAttachment(
                media_id=item.get("media_id") or item.get("id"),
                mime_type=item.get("mime_type"),
                url=item.get("url"),
                sha256=item.get("sha256"),
                caption=item.get("caption"),
            )
            for item in attachments
        ]

    media_id = payload.get("media_id")
    media_url = payload.get("media_url") or payload.get("url")
    mime_type = payload.get("mime_type")
    caption = payload.get("caption")
    sha256 = payload.get("sha256")

    if media_id or media_url:
        return [
            MediaAttachment(
                media_id=media_id,
                mime_type=mime_type,
                url=media_url,
                sha256=sha256,
                caption=caption,
            )
        ]

    return []


def build_location(payload: dict[str, object]) -> LocationPayload | None:
    location = payload.get("location")
    if isinstance(location, dict):
        return LocationPayload(
            latitude=location["latitude"],
            longitude=location["longitude"],
            name=location.get("name"),
            address=location.get("address"),
        )

    if payload.get("latitude") is not None and payload.get("longitude") is not None:
        return LocationPayload(
            latitude=payload["latitude"],
            longitude=payload["longitude"],
            name=payload.get("location_name"),
            address=payload.get("location_address"),
        )

    return None


def build_interactive(payload: dict[str, object]) -> InteractivePayload | None:
    interactive = payload.get("interactive")
    if isinstance(interactive, dict):
        reply_type = interactive.get("reply_type") or interactive.get("type") or "button"
        return InteractivePayload(
            reply_type=InteractiveReplyType(reply_type),
            reply_id=interactive.get("reply_id") or interactive.get("id"),
            title=interactive.get("title"),
            payload=interactive.get("payload") or {},
        )

    button_id = payload.get("button_id")
    if button_id:
        return InteractivePayload(
            reply_type=InteractiveReplyType.BUTTON,
            reply_id=button_id,
            title=payload.get("button_title"),
            payload={},
        )

    return None


def ensure_message_id(
    *,
    channel: str,
    external_message_id: str | None,
    sender_hint: str | None,
) -> str:
    if external_message_id and str(external_message_id).strip():
        return str(external_message_id).strip()
    return build_message_fingerprint(
        channel=channel,
        external_message_id=str(external_message_id or "missing"),
        sender_id=str(sender_hint or "unknown"),
    )
