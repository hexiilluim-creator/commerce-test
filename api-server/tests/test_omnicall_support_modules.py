from __future__ import annotations

from omnicall_v9.observability.context import build_log_context
from omnicall_v9.observability.events import OBS_EVENT_NAMES
from omnicall_v9.types.unified_message import ChannelType, DirectionType, MessageKind, UnifiedMessage
from omnicall_v9.utils.ids import build_idempotency_key, build_message_fingerprint, build_trace_id


def test_build_message_fingerprint_is_deterministic_and_prefixed() -> None:
    first = build_message_fingerprint(
        channel="whatsapp",
        external_message_id="wamid.123",
        sender_id="client-42",
        extra="body-hash",
    )
    second = build_message_fingerprint(
        channel="whatsapp",
        external_message_id="wamid.123",
        sender_id="client-42",
        extra="body-hash",
    )
    third = build_message_fingerprint(
        channel="whatsapp",
        external_message_id="wamid.123",
        sender_id="client-42",
        extra="other",
    )

    assert first == second
    assert first.startswith("wha-")
    assert len(first) == 36
    assert third != first


def test_build_trace_id_and_idempotency_key_formats() -> None:
    trace_id = build_trace_id()

    assert trace_id.startswith("oc9-")
    assert len(trace_id) == 20
    assert build_idempotency_key(channel="instagram", store_id=12, message_id="abc") == (
        "omnicall:dedup:instagram:12:abc"
    )
    assert build_idempotency_key(channel="tiktok", store_id=None, message_id="missing") == (
        "omnicall:dedup:tiktok:none:missing"
    )


def test_build_log_context_extracts_observability_fields() -> None:
    message = UnifiedMessage(
        message_id="msg-1",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.TEXT,
        store_id=7,
        trace_id="oc9-fixed-trace",
        schema_version="v9.9",
    )

    assert build_log_context(message) == {
        "schema_version": "v9.9",
        "channel": ChannelType.WHATSAPP,
        "message_kind": MessageKind.TEXT,
        "store_id": 7,
        "message_id": "msg-1",
        "trace_id": "oc9-fixed-trace",
    }


def test_observability_event_names_are_unique_and_namespaced() -> None:
    assert len(OBS_EVENT_NAMES) == len(set(OBS_EVENT_NAMES))
    assert all(name.startswith("omnicall_v9.") for name in OBS_EVENT_NAMES)
    assert "omnicall_v9.pipeline.accepted" in OBS_EVENT_NAMES
    assert "omnicall_v9.dedup.skipped" in OBS_EVENT_NAMES
