"""tests/test_bloc10.py — Tests unitaires BLOC 10 OmniCall V9.

Couvre :
  - dispatch_v9 : flag disabled, circuit open, pipeline reject, credits, send success/fail, V8 fallback
  - Senders : WhatsAppV9Sender, InstagramV9Sender, TikTokV9Sender
  - DispatchResult : success/bool
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omnicall_v9.bloc10 import DispatchResult, dispatch_v9
from omnicall_v9.pipeline.minimal import AgentRoute, ConversationState, PipelineResult
from omnicall_v9.senders.base import AgentReply, ReplyKind, SendResult, get_sender, register_sender
from omnicall_v9.types.unified_message import ChannelType, DirectionType, IdentityRef, MessageKind, UnifiedMessage

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_unified(text: str = "bonjour", channel: ChannelType = ChannelType.WHATSAPP) -> UnifiedMessage:
    return UnifiedMessage(
        message_id="msg_test_001",
        channel=channel,
        direction=DirectionType.INBOUND,
        message_kind=MessageKind.TEXT,
        text=text,
        store_id=42,
        sender=IdentityRef(phone="+21699000001"),
    )


def _make_store(store_id: int = 42) -> MagicMock:
    store = MagicMock()
    store.id = store_id
    store.name = "Boutique Test"
    store.max_discount_pct = 10
    return store


def _make_pipeline_result(accepted: bool = True, route: AgentRoute = AgentRoute.QUALIFICATION) -> PipelineResult:
    return PipelineResult(
        accepted=accepted,
        route=route,
        handler_name="qualification_agent",
        fsm_state=ConversationState.QUALIFICATION,
    )


# ── Tests DispatchResult ──────────────────────────────────────────────────────

class TestDispatchResult:
    def test_success_true_when_dispatched_and_send_ok(self):
        send = SendResult(success=True, channel=ChannelType.WHATSAPP, recipient_id="+21699000001")
        result = DispatchResult(dispatched_by_v9=True, send_result=send)
        assert result.success is True

    def test_success_false_when_v8_fallback(self):
        result = DispatchResult(dispatched_by_v9=False, send_result=None, v8_fallback_reason="flag_disabled")
        assert result.success is False

    def test_success_false_when_send_failed(self):
        send = SendResult(success=False, channel=ChannelType.WHATSAPP, recipient_id="+21699000001", error="timeout")
        result = DispatchResult(dispatched_by_v9=True, send_result=send)
        assert result.success is False


# ── Tests dispatch_v9 (flag disabled) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_v9_flag_disabled():
    """Si le flag V9 est désactivé, retourne V8 fallback immédiatement."""
    with patch("omnicall_v9.bloc10.feature_flag", return_value=False):
        result = await dispatch_v9(
            _make_unified(),
            db=AsyncMock(),
            store=_make_store(),
        )
    assert result.dispatched_by_v9 is False
    assert result.v8_fallback_reason == "flag_disabled"


@pytest.mark.asyncio
async def test_dispatch_v9_circuit_open():
    """Si le circuit breaker est ouvert, retourne V8 fallback."""
    with patch("omnicall_v9.bloc10.feature_flag", return_value=True), \
         patch("omnicall_v9.bloc10.v9_circuit") as mock_cb:
        mock_cb.is_v9_safe.return_value = False
        result = await dispatch_v9(_make_unified(), db=AsyncMock(), store=_make_store())
    assert result.dispatched_by_v9 is False
    assert result.v8_fallback_reason == "circuit_open"


@pytest.mark.asyncio
async def test_dispatch_v9_pipeline_rejected():
    """Si le pipeline rejette le message, retourne V8 fallback."""
    from omnicall_v9.pipeline.safe_boundary import SafeProcessResult

    safe_result = SafeProcessResult(accepted=False, reason="status_event_skip", processor_result=None)

    with patch("omnicall_v9.bloc10.feature_flag", return_value=True), \
         patch("omnicall_v9.bloc10.v9_circuit") as mock_cb, \
         patch("omnicall_v9.bloc10.safe_process_unified", return_value=safe_result):
        mock_cb.is_v9_safe.return_value = True
        result = await dispatch_v9(_make_unified(), db=AsyncMock(), store=_make_store())
    assert result.dispatched_by_v9 is False
    assert "pipeline_rejected" in result.v8_fallback_reason


@pytest.mark.asyncio
async def test_dispatch_v9_credits_exhausted():
    """Si les crédits sont épuisés, retourne V8 fallback."""
    from omnicall_v9.pipeline.safe_boundary import SafeProcessResult

    safe_result = SafeProcessResult(
        accepted=True,
        processor_result=_make_pipeline_result(),
    )

    with patch("omnicall_v9.bloc10.feature_flag", return_value=True), \
         patch("omnicall_v9.bloc10.v9_circuit") as mock_cb, \
         patch("omnicall_v9.bloc10.safe_process_unified", return_value=safe_result), \
         patch("omnicall_v9.bloc10._check_and_deduct_credits", new=AsyncMock(return_value=False)):
        mock_cb.is_v9_safe.return_value = True
        result = await dispatch_v9(_make_unified(), db=AsyncMock(), store=_make_store())
    assert result.dispatched_by_v9 is False
    assert result.v8_fallback_reason == "credits_exhausted"


@pytest.mark.asyncio
async def test_dispatch_v9_full_success():
    """Pipeline réussi + agent LLM + envoi → dispatched_by_v9=True."""
    from omnicall_v9.pipeline.safe_boundary import SafeProcessResult
    from omnicall_v9.senders.base import BaseSender

    safe_result = SafeProcessResult(
        accepted=True,
        processor_result=_make_pipeline_result(route=AgentRoute.QUALIFICATION),
    )

    mock_send_result = SendResult(
        success=True, channel=ChannelType.WHATSAPP, recipient_id="+21699000001",
        provider_message_id="wamid.test123",
    )
    mock_sender = MagicMock(spec=BaseSender)
    mock_sender.send = AsyncMock(return_value=mock_send_result)
    mock_sender._store = None

    with patch("omnicall_v9.bloc10.feature_flag", return_value=True), \
         patch("omnicall_v9.bloc10.v9_circuit") as mock_cb, \
         patch("omnicall_v9.bloc10.safe_process_unified", return_value=safe_result), \
         patch("omnicall_v9.bloc10._check_and_deduct_credits", new=AsyncMock(return_value=True)), \
         patch("omnicall_v9.bloc10._call_qualification_agent", new=AsyncMock(return_value="Bonjour ! Comment puis-je vous aider ?")), \
         patch("omnicall_v9.bloc10.get_sender", return_value=mock_sender):
        mock_cb.is_v9_safe.return_value = True
        mock_cb.record_success = MagicMock()

        result = await dispatch_v9(_make_unified(), db=AsyncMock(), store=_make_store())

    assert result.dispatched_by_v9 is True
    assert result.success is True
    assert result.send_result.provider_message_id == "wamid.test123"
    mock_cb.record_success.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_v9_send_failure_updates_circuit():
    """Si l'envoi échoue, le circuit breaker doit enregistrer l'erreur."""
    from omnicall_v9.pipeline.safe_boundary import SafeProcessResult
    from omnicall_v9.senders.base import BaseSender

    safe_result = SafeProcessResult(
        accepted=True,
        processor_result=_make_pipeline_result(),
    )

    mock_send_result = SendResult(
        success=False, channel=ChannelType.WHATSAPP, recipient_id="+21699000001", error="timeout"
    )
    mock_sender = MagicMock(spec=BaseSender)
    mock_sender.send = AsyncMock(return_value=mock_send_result)
    mock_sender._store = None

    with patch("omnicall_v9.bloc10.feature_flag", return_value=True), \
         patch("omnicall_v9.bloc10.v9_circuit") as mock_cb, \
         patch("omnicall_v9.bloc10.safe_process_unified", return_value=safe_result), \
         patch("omnicall_v9.bloc10._check_and_deduct_credits", new=AsyncMock(return_value=True)), \
         patch("omnicall_v9.bloc10._call_qualification_agent", new=AsyncMock(return_value="Bonjour")), \
         patch("omnicall_v9.bloc10.get_sender", return_value=mock_sender):
        mock_cb.is_v9_safe.return_value = True
        mock_cb.record_error = MagicMock()

        result = await dispatch_v9(_make_unified(), db=AsyncMock(), store=_make_store())

    assert result.dispatched_by_v9 is True
    assert result.success is False
    mock_cb.record_error.assert_called_once()


# ── Tests Senders ─────────────────────────────────────────────────────────────

class TestSenderRegistry:
    def test_whatsapp_sender_registered(self):
        """WhatsApp sender doit être enregistré au chargement du module."""
        import omnicall_v9.senders.whatsapp  # noqa: F401
        sender = get_sender(ChannelType.WHATSAPP)
        assert sender is not None
        assert sender.channel == ChannelType.WHATSAPP

    def test_instagram_sender_registered(self):
        import omnicall_v9.senders.social  # noqa: F401
        sender = get_sender(ChannelType.INSTAGRAM)
        assert sender is not None

    def test_facebook_sender_registered(self):
        import omnicall_v9.senders.social  # noqa: F401
        sender = get_sender(ChannelType.FACEBOOK)
        assert sender is not None

    def test_tiktok_sender_registered(self):
        import omnicall_v9.senders.social  # noqa: F401
        sender = get_sender(ChannelType.TIKTOK)
        assert sender is not None

    def test_unknown_channel_returns_none(self):
        result = get_sender(ChannelType.UNKNOWN)
        assert result is None


@pytest.mark.asyncio
async def test_whatsapp_sender_text_success():
    """WhatsAppV9Sender.send() appelle WhatsAppClient.send_text() correctement."""
    from omnicall_v9.senders.whatsapp import WhatsAppV9Sender

    mock_client = MagicMock()
    mock_client.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.abc"}]})

    reply = AgentReply(
        recipient_id="+21699000001",
        channel=ChannelType.WHATSAPP,
        kind=ReplyKind.TEXT,
        text="Bonjour !",
        store_id=42,
    )

    sender = WhatsAppV9Sender()
    with patch("omnicall_v9.senders.whatsapp.WhatsAppV9Sender._get_client", return_value=mock_client):
        result = await sender.send(reply)

    assert result.success is True
    assert result.provider_message_id == "wamid.abc"
    mock_client.send_text.assert_called_once_with("+21699000001", "Bonjour !")


@pytest.mark.asyncio
async def test_whatsapp_sender_retries_on_error():
    """WhatsAppV9Sender réessaie 3 fois avant d'échouer."""
    from omnicall_v9.senders.whatsapp import WhatsAppV9Sender

    mock_client = MagicMock()
    mock_client.send_text = AsyncMock(side_effect=Exception("network error"))

    reply = AgentReply(
        recipient_id="+21699000001",
        channel=ChannelType.WHATSAPP,
        kind=ReplyKind.TEXT,
        text="Test",
        store_id=42,
    )

    sender = WhatsAppV9Sender()
    with patch("omnicall_v9.senders.whatsapp.WhatsAppV9Sender._get_client", return_value=mock_client), \
         patch("asyncio.sleep", new=AsyncMock()):
        result = await sender.send(reply)

    assert result.success is False
    assert "network error" in result.error
    assert mock_client.send_text.call_count == 3  # 3 tentatives


@pytest.mark.asyncio
async def test_tiktok_sender_graceful_degradation():
    """TikTokV9Sender retourne success=False gracieusement si API non disponible."""
    from omnicall_v9.senders.social import TikTokV9Sender

    mock_client = MagicMock()
    mock_client.send_text = AsyncMock(side_effect=NotImplementedError("Business Partner required"))

    reply = AgentReply(
        recipient_id="tiktok_user_123",
        channel=ChannelType.TIKTOK,
        kind=ReplyKind.TEXT,
        text="Bonjour",
        store_id=42,
    )

    sender = TikTokV9Sender()
    with patch("omnicall_v9.senders.social.TikTokClient") as MockTikTok:
        MockTikTok.from_settings.return_value = mock_client
        result = await sender.send(reply)

    assert result.success is False
    assert "Business Partner" in result.error


# ── Test AgentReply construction ──────────────────────────────────────────────

class TestAgentReply:
    def test_text_reply(self):
        reply = AgentReply(
            recipient_id="+21699000001",
            channel=ChannelType.WHATSAPP,
            kind=ReplyKind.TEXT,
            text="Test",
            store_id=42,
        )
        assert reply.kind == ReplyKind.TEXT
        assert reply.text == "Test"
        assert reply.channel == ChannelType.WHATSAPP

    def test_interactive_reply_with_buttons(self):
        reply = AgentReply(
            recipient_id="+21699000001",
            channel=ChannelType.WHATSAPP,
            kind=ReplyKind.INTERACTIVE,
            interactive_type="button",
            interactive_body="Choisissez :",
            interactive_buttons=[
                {"id": "btn_1", "title": "Voir catalogue"},
                {"id": "btn_2", "title": "Commander"},
            ],
            store_id=42,
        )
        assert len(reply.interactive_buttons) == 2
        assert reply.interactive_buttons[0]["title"] == "Voir catalogue"
