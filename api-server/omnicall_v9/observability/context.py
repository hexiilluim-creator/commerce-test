"""Helpers to create stable log/metric labels for OmniCall V9."""

from __future__ import annotations

from omnicall_v9.types.unified_message import UnifiedMessage


def build_log_context(message: UnifiedMessage) -> dict[str, object]:
    return {
        "schema_version": message.schema_version,
        "channel": message.channel,
        "message_kind": message.message_kind,
        "store_id": message.store_id,
        "message_id": message.message_id,
        "trace_id": message.trace_id,
    }
