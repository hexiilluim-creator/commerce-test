from datetime import UTC, datetime

import pytest

from omnicall_v9.types.unified_message import (
    ChannelType,
    DirectionType,
    IdentityRef,
    MediaAttachment,
    MessageKind,
    UnifiedMessage,
)


def test_unified_message_logic():
    msg = UnifiedMessage(
        message_id="test_123",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.TEXT,
        text="  Hello World  ",
        sender=IdentityRef(external_id="ext_1"),
    )
    
    assert msg.has_text() is True
    assert msg.has_media() is False
    assert msg.is_actionable() is True
    assert msg.token_budget_estimate() >= 10

def test_unified_message_empty_text():
    msg = UnifiedMessage(
        message_id="test_123",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.TEXT,
        text="   ",
    )
    assert msg.has_text() is False

def test_unified_message_with_media():
    msg = UnifiedMessage(
        message_id="test_123",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.IMAGE,
        media=[MediaAttachment(media_id="m1", mime_type="image/jpeg")]
    )
    assert msg.has_media() is True
    assert msg.token_budget_estimate() > 80

def test_unified_message_not_actionable():
    # Outbound is not actionable for the agent
    msg_out = UnifiedMessage(
        message_id="test_123",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.OUTBOUND,
        message_kind=MessageKind.TEXT,
    )
    assert msg_out.is_actionable() is False
    
    # Status messages are not actionable
    msg_status = UnifiedMessage(
        message_id="test_123",
        channel=ChannelType.WHATSAPP,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.STATUS,
    )
    assert msg_status.is_actionable() is False
