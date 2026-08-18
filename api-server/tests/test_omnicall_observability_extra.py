from __future__ import annotations

import logging

from omnicall_v9.observability.logger import get_omnicall_logger, log_pipeline_event
from omnicall_v9.observability.shadow_observer import ShadowObserver
from omnicall_v9.pipeline.safe_boundary import safe_process_unified
from omnicall_v9.types.unified_message import ChannelType, DirectionType, MessageKind, UnifiedMessage


def _make_message() -> UnifiedMessage:
    return UnifiedMessage(
        message_id="msg-obs-1",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.TEXT,
        text="bonjour",
        store_id=12,
        trace_id="trace-fixed",
    )



def test_safe_process_unified_returns_result_metadata_on_success() -> None:
    message = _make_message()

    result = safe_process_unified(message, lambda msg: type("R", (), {"accepted": True, "reason": "ok", "echo": msg.text})())

    assert result.accepted is True
    assert result.reason == "ok"
    assert result.processor_result.echo == "bonjour"
    assert result.duration_ms >= 0



def test_safe_process_unified_captures_exception_without_propagation(caplog) -> None:
    message = _make_message()

    def _boom(_message: UnifiedMessage) -> object:
        raise RuntimeError("pipeline broke")

    with caplog.at_level(logging.ERROR):
        result = safe_process_unified(message, _boom)

    assert result.accepted is False
    assert result.reason == "pipeline_exception"
    assert result.error_type == "RuntimeError"
    assert any(record.message == "omnicall_v9.safe_boundary.pipeline_error" for record in caplog.records)



def test_log_pipeline_event_emits_structured_payload(caplog) -> None:
    message = _make_message()

    with caplog.at_level(logging.INFO, logger="omnicall_v9"):
        log_pipeline_event("omnicall_v9.pipeline.accepted", message, route="qualification")

    record = next(record for record in caplog.records if record.name == "omnicall_v9")
    assert record.message == "omnicall_v9.pipeline.accepted"
    assert record.omnicall["message_id"] == "msg-obs-1"
    assert record.omnicall["route"] == "qualification"



def test_get_omnicall_logger_returns_named_logger() -> None:
    assert get_omnicall_logger().name == "omnicall_v9"



def test_shadow_observer_tracks_acceptance_errors_and_reset() -> None:
    observer = ShadowObserver()
    observer.record_shadow_processed("whatsapp", accepted=True, route="qualification")
    observer.record_shadow_processed("whatsapp", accepted=False, error_type="sender_timeout")
    observer.record_normalize_error("instagram", "schema")

    report = observer.get_report()

    assert report["shadow_mode"] == "active"
    assert report["total_events"] == 3
    assert report["channels"]["whatsapp"]["accepted"] == 1
    assert report["channels"]["whatsapp"]["rejected"] == 1
    assert report["channels"]["whatsapp"]["routes"] == {"qualification": 1}
    assert report["channels"]["whatsapp"]["error_types"] == {"sender_timeout": 1}
    assert report["channels"]["instagram"]["normalize_errors"] == 1
    assert report["channels"]["instagram"]["error_types"] == {"normalize.schema": 1}

    observer.reset()
    reset_report = observer.get_report()
    assert reset_report["total_events"] == 0
    assert reset_report["channels"] == {}
