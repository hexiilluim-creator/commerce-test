from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from services.social_agent import _get_or_create_social_customer, _get_store, handle_social_message, handle_social_message_sync


@pytest.mark.asyncio
async def test_get_or_create_social_customer_existing_and_new():
    store = SimpleNamespace(id=3, language="fr")
    existing = SimpleNamespace(id=9)
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=result)
    assert await _get_or_create_social_customer(db, store, "sender", "instagram") is existing

    result.scalar_one_or_none.return_value = None
    created = SimpleNamespace(id=10)
    def add(obj):
        obj.id = 10
    db.add.side_effect = add
    db.flush = AsyncMock()
    customer = await _get_or_create_social_customer(db, store, "sender2", "facebook")
    assert customer.channel == "facebook"
    assert customer.social_sender_id == "sender2"
    assert customer.whatsapp_phone == "facebook_sender2"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_store_active_lookup():
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(id=3, is_active=True)
    db.execute = AsyncMock(return_value=result)
    assert (await _get_store(db, 3)).id == 3


@pytest.mark.asyncio
async def test_handle_social_message_dropped_and_missing_store():
    assert await handle_social_message(0, "instagram", "s", "hi") == {"status": "dropped", "reason": "store_id_not_resolved"}
    async def empty_db():
        db = MagicMock()
        db.execute = AsyncMock()
        yield db
    with patch("services.social_agent.get_db", empty_db), patch("services.social_agent._get_store", new=AsyncMock(return_value=None)):
        data = await handle_social_message(3, "instagram", "s", "hi")
    assert data == {"status": "error", "reason": "store_not_found"}


def test_sync_wrapper_ignores_missing_context():
    assert handle_social_message_sync(None, "instagram", "s", "hi") is None
    assert handle_social_message_sync(1, "instagram", None, "hi") is None


@pytest.mark.asyncio
async def test_handle_social_message_channel_not_configured_and_unknown_type():
    async def db_stream():
        yield MagicMock()
    store = SimpleNamespace(id=3)
    router = SimpleNamespace(is_configured=False, send_text=AsyncMock())
    with patch("services.social_agent.get_db", db_stream), \
         patch("services.social_agent._get_store", new=AsyncMock(return_value=store)), \
         patch("services.social_agent._get_or_create_social_customer", new=AsyncMock(return_value=SimpleNamespace(id=8))), \
         patch("services.social_agent.ChannelRouter", return_value=router):
        assert (await handle_social_message(3, "instagram", "s", "hi"))["reason"] == "channel_not_configured"
    router.is_configured = True
    with patch("services.social_agent.get_db", db_stream), \
         patch("services.social_agent._get_store", new=AsyncMock(return_value=store)), \
         patch("services.social_agent._get_or_create_social_customer", new=AsyncMock(return_value=SimpleNamespace(id=8))), \
         patch("services.social_agent.ChannelRouter", return_value=router):
        out = await handle_social_message(3, "instagram", "s", None, message_type="unknown")
    assert out["status"] == "ok" and router.send_text.await_count == 1


@pytest.mark.asyncio
async def test_handle_social_message_dispatch_success_and_ai_fallback():
    async def db_stream():
        yield MagicMock()
    store = SimpleNamespace(id=3)
    router = SimpleNamespace(is_configured=True, send_text=AsyncMock())
    customer = SimpleNamespace(id=8)
    with patch("services.social_agent.get_db", db_stream), \
         patch("services.social_agent._get_store", new=AsyncMock(return_value=store)), \
         patch("services.social_agent._get_or_create_social_customer", new=AsyncMock(return_value=customer)), \
         patch("services.social_agent.ChannelRouter", return_value=router), \
         patch("services.tasks._dispatch_by_business_type", new=AsyncMock(return_value="structured reply"), create=True):
        out = await handle_social_message(3, "facebook", "s", "hello")
    assert out["reply"] == "structured reply"
    with patch("services.social_agent.get_db", db_stream), \
         patch("services.social_agent._get_store", new=AsyncMock(return_value=store)), \
         patch("services.social_agent._get_or_create_social_customer", new=AsyncMock(return_value=customer)), \
         patch("services.social_agent.ChannelRouter", return_value=router), \
         patch("services.tasks._dispatch_by_business_type", new=AsyncMock(side_effect=RuntimeError("dispatch")), create=True), \
         patch("services.social_agent.ai_agent.handle_text_message", new=AsyncMock(return_value="fallback")):
        out = await handle_social_message(3, "facebook", "s", "hello")
    assert out["reply"] == "fallback"


@pytest.mark.asyncio
async def test_handle_social_message_image_ack_and_handle_social_event_normalizes_payload():
    async def db_stream():
        yield MagicMock()
    store = SimpleNamespace(id=3)
    router = SimpleNamespace(is_configured=True, send_text=AsyncMock())
    with patch("services.social_agent.get_db", db_stream), \
         patch("services.social_agent._get_store", new=AsyncMock(return_value=store)), \
         patch("services.social_agent._get_or_create_social_customer", new=AsyncMock(return_value=SimpleNamespace(id=8))), \
         patch("services.social_agent.ChannelRouter", return_value=router):
        out = await handle_social_message(3, "instagram", "s", None, message_type="image", attachments=[{"url": "x"}])
    assert out["status"] == "received_no_vision"
    with patch("services.social_agent.handle_social_message", new=AsyncMock(return_value={"status": "ok"})) as handler:
        result = await __import__("services.social_agent", fromlist=["handle_social_event"]).handle_social_event(
            platform="instagram", store_id=3, payload={"entry": [{"messaging": [{"sender": {"id": "s"}, "message": {"text": "hi"}}]}]}, db=MagicMock())
    assert result == {"status": "ok"}
    assert handler.await_args.kwargs["channel"] == "instagram"
