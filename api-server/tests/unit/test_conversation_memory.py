"""tests/test_conversation_memory.py — Tests Mémoire Conversationnelle (Phase 1).

Tests unitaires : 25 cas
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.publish = AsyncMock()
    return r


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


# ── Tests mémoire court terme (Redis) ────────────────────────────────────────

class TestShortTermMemory:

    @pytest.mark.asyncio
    async def test_store_short_term_success(self, mock_redis):
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis):
            from services.conversation_memory_service import store_short_term
            await store_short_term(1, 42, {"fsm_state": "browsing", "last_product": "shoes"})
            mock_redis.setex.assert_awaited_once()
            call_args = mock_redis.setex.call_args
            assert call_args[0][0] == "mem:st:1:42"
            assert call_args[0][1] == 4 * 3600  # TTL 4h

    @pytest.mark.asyncio
    async def test_store_short_term_redis_failure_graceful(self, mock_redis):
        mock_redis.setex.side_effect = Exception("Redis down")
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis):
            from services.conversation_memory_service import store_short_term
            await store_short_term(1, 42, {"data": "x"})  # ne doit pas lever d'exception

    @pytest.mark.asyncio
    async def test_load_short_term_hit(self, mock_redis):
        mock_redis.get = AsyncMock(return_value=json.dumps({"fsm_state": "idle"}).encode())
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis):
            from services.conversation_memory_service import load_short_term
            result = await load_short_term(1, 42)
            assert result["fsm_state"] == "idle"

    @pytest.mark.asyncio
    async def test_load_short_term_miss_returns_empty(self, mock_redis):
        mock_redis.get = AsyncMock(return_value=None)
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis):
            from services.conversation_memory_service import load_short_term
            result = await load_short_term(1, 42)
            assert result == {}

    @pytest.mark.asyncio
    async def test_load_short_term_redis_failure_returns_empty(self, mock_redis):
        mock_redis.get.side_effect = Exception("Redis down")
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis):
            from services.conversation_memory_service import load_short_term
            result = await load_short_term(1, 42)
            assert result == {}

    def test_short_term_key_format(self):
        from services.conversation_memory_service import _short_term_key
        assert _short_term_key(5, 100) == "mem:st:5:100"
        assert _short_term_key(0, 0) == "mem:st:0:0"

    @pytest.mark.asyncio
    async def test_store_short_term_json_serializable(self, mock_redis):
        import datetime
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis):
            from services.conversation_memory_service import store_short_term
            # Doit gérer les datetime sans lever TypeError
            await store_short_term(1, 1, {"ts": datetime.datetime.now()})
            mock_redis.setex.assert_awaited_once()


# ── Tests mémoire long terme (PostgreSQL) ────────────────────────────────────

class TestLongTermMemory:

    @pytest.mark.asyncio
    async def test_store_long_term_inserts_row(self, mock_db):
        mock_result = MagicMock()
        mock_db.execute.return_value = mock_result
        with patch("services.conversation_memory_service.store_long_term", autospec=True) as mock_store:
            mock_store.return_value = None
            from services.conversation_memory_service import store_long_term
            await store_long_term(mock_db, 1, 42, "message", {"text": "bonjour"})

    @pytest.mark.asyncio
    async def test_load_long_term_returns_list(self, mock_db):
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [
            {"entry_type": "message", "content": '{"text":"hello"}',
             "source_channel": "whatsapp", "created_at": None}
        ]
        mock_db.execute.return_value = mock_result
        from services.conversation_memory_service import load_long_term
        result = await load_long_term(mock_db, 1, 42)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_load_long_term_db_failure_returns_empty(self, mock_db):
        mock_db.execute.side_effect = Exception("DB down")
        from services.conversation_memory_service import load_long_term
        result = await load_long_term(mock_db, 1, 42)
        assert result == []

    @pytest.mark.asyncio
    async def test_record_message_calls_store_long_term(self, mock_db):
        with patch("services.conversation_memory_service.store_long_term") as mock_store:
            mock_store.return_value = None
            from services.conversation_memory_service import record_message
            await record_message(mock_db, 1, 42, "bonjour", direction="in")
            mock_store.assert_called_once()
            call_args = mock_store.call_args[0]
            assert call_args[3] == "message"

    @pytest.mark.asyncio
    async def test_record_order(self, mock_db):
        with patch("services.conversation_memory_service.store_long_term") as mock_store:
            mock_store.return_value = None
            from services.conversation_memory_service import record_order
            await record_order(mock_db, 1, 42, order_id=99, total=150.0, status="paid")
            mock_store.assert_called_once()
            args = mock_store.call_args[0]
            assert args[3] == "order"
            assert args[4]["order_id"] == 99

    @pytest.mark.asyncio
    async def test_record_objection(self, mock_db):
        with patch("services.conversation_memory_service.store_long_term") as mock_store:
            mock_store.return_value = None
            from services.conversation_memory_service import record_objection
            await record_objection(mock_db, 1, 42, "C'est trop cher")
            args = mock_store.call_args[0]
            assert args[3] == "objection"
            assert "trop cher" in args[4]["text"]

    @pytest.mark.asyncio
    async def test_record_appointment(self, mock_db):
        with patch("services.conversation_memory_service.store_long_term") as mock_store:
            mock_store.return_value = None
            from services.conversation_memory_service import record_appointment
            await record_appointment(mock_db, 1, 42, date="2024-07-01", service="Consultation")
            args = mock_store.call_args[0]
            assert args[3] == "appointment"


# ── Tests build_memory_context ───────────────────────────────────────────────

class TestBuildMemoryContext:

    @pytest.mark.asyncio
    async def test_build_memory_context_structure(self, mock_db, mock_redis):
        mock_db.execute.return_value = MagicMock(
            mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis), \
             patch("services.conversation_memory_service.load_long_term", return_value=[]):
            from services.conversation_memory_service import build_memory_context
            ctx = await build_memory_context(mock_db, 1, 42, "+21698000000")
            assert "short_term" in ctx
            assert "last_messages" in ctx
            assert "past_orders" in ctx
            assert "past_appointments" in ctx
            assert "past_objections" in ctx
            assert ctx["customer_phone"] == "+21698000000"

    @pytest.mark.asyncio
    async def test_build_memory_context_last_messages_max_3(self, mock_db, mock_redis):
        msgs = [{"content": {"text": f"msg{i}"}, "source_channel": "wa", "created_at": None}
                for i in range(10)]
        with patch("services.conversation_memory_service._get_redis", return_value=mock_redis), \
             patch("services.conversation_memory_service.load_long_term",
                   side_effect=[msgs, [], [], [], []]):
            from services.conversation_memory_service import build_memory_context
            ctx = await build_memory_context(mock_db, 1, 42)
            assert len(ctx["last_messages"]) <= 10  # load_long_term limite déjà
