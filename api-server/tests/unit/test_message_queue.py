"""tests/test_message_queue.py — Tests file de messages Redis Streams (Phase 2).

Couverture :
  - push_message : push basique, déduplication, fallback si Redis absent
  - consume_messages : traitement, retry, DLQ
  - ensure_consumer_group : création idempotente
  - get_queue_stats : métriques de la file
  - compute_paymee_checksum : importabilité
"""
import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ENCRYPTION_KEY", "mQ76Y4LQdjfKjD42QikIYjneih_7xToYtL6vhfVqlh0=")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-32-chars-minimum-ok!")
os.environ.setdefault("SERVER_DOMAIN", "https://test.example.com")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-0000000000000000000000000000000000000000000000")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-token")


def _make_mock_redis():
    r = AsyncMock()
    r.ping = AsyncMock(return_value=True)
    r.set = AsyncMock(return_value=True)
    r.xadd = AsyncMock(return_value=b"1234567890-0")
    r.xlen = AsyncMock(return_value=0)
    r.exists = AsyncMock(return_value=0)
    r.xpending = AsyncMock(return_value={"pending": 0})
    r.xgroup_create = AsyncMock()
    r.xreadgroup = AsyncMock(return_value=[])
    r.xack = AsyncMock()
    r.xautoclaim = AsyncMock(return_value=("0-0", []))
    return r


class TestPushMessage:

    @pytest.mark.asyncio
    async def test_push_returns_stream_entry_id(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            result = await message_queue.push_message({
                "message_id": "wamid.001",
                "store_id": 7,
                "body": "Bonjour",
            })
        assert result is not None
        mock_r.xadd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deduplication_returns_none_for_duplicate(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        # Premier appel : set NX réussit (nouveau message)
        # Deuxième appel : set NX échoue (doublon)
        mock_r.set = AsyncMock(side_effect=[True, False])
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            result1 = await message_queue.push_message({"message_id": "wamid.dup", "store_id": 1, "body": "test"})
            result2 = await message_queue.push_message({"message_id": "wamid.dup", "store_id": 1, "body": "test"})
        assert result1 is not None
        assert result2 is None  # doublon ignoré

    @pytest.mark.asyncio
    async def test_push_returns_none_if_redis_unavailable(self):
        from services import message_queue
        with patch.object(message_queue, "_get_redis", return_value=None):
            result = await message_queue.push_message({"message_id": "m1", "store_id": 1})
        assert result is None

    @pytest.mark.asyncio
    async def test_push_without_message_id_no_dedup(self):
        """Messages sans ID ne sont pas dédupliqués mais sont quand même poussés."""
        from services import message_queue
        mock_r = _make_mock_redis()
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            result = await message_queue.push_message({"store_id": 1, "body": "test"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_push_handles_redis_exception_gracefully(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        mock_r.xadd.side_effect = Exception("Redis connection refused")
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            result = await message_queue.push_message({"message_id": "m1", "store_id": 1})
        assert result is None  # fail gracefully

    @pytest.mark.asyncio
    async def test_push_sets_maxlen(self):
        """Les messages sont poussés avec une limite de taille du stream."""
        from services import message_queue
        mock_r = _make_mock_redis()
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            await message_queue.push_message({"message_id": "m2", "store_id": 1})
        call_kwargs = mock_r.xadd.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        assert kwargs.get("maxlen") or kwargs.get("approximate")


class TestEnsureConsumerGroup:

    @pytest.mark.asyncio
    async def test_creates_group(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            await message_queue.ensure_consumer_group()
        mock_r.xgroup_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ignores_busygroup_error(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        mock_r.xgroup_create.side_effect = Exception("BUSYGROUP Consumer Group name already exists")
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            await message_queue.ensure_consumer_group()  # ne doit pas lever

    @pytest.mark.asyncio
    async def test_handles_redis_unavailable(self):
        from services import message_queue
        with patch.object(message_queue, "_get_redis", return_value=None):
            await message_queue.ensure_consumer_group()  # ne doit pas lever


class TestProcessEntry:

    @pytest.mark.asyncio
    async def test_calls_handler_and_acks(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        handler = AsyncMock()
        payload = {"message_id": "m1", "store_id": 7, "body": "test"}
        fields = {b"payload": json.dumps(payload).encode(), b"retries": b"0"}

        await message_queue._process_entry(mock_r, b"123-0", fields, "w0", handler)

        handler.assert_awaited_once_with(payload)
        mock_r.xack.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_on_handler_failure(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        handler = AsyncMock(side_effect=Exception("OpenAI timeout"))
        payload = {"message_id": "m1", "store_id": 7, "body": "test"}
        fields = {b"payload": json.dumps(payload).encode(), b"retries": b"1"}

        await message_queue._process_entry(mock_r, b"123-0", fields, "w0", handler)

        # Après un échec, le message est re-injecté avec retries+1
        mock_r.xadd.assert_awaited()  # re-injection
        mock_r.xack.assert_awaited()  # ack original

    @pytest.mark.asyncio
    async def test_max_retries_sends_to_dlq(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        mock_r.exists = AsyncMock(return_value=0)
        handler = AsyncMock(side_effect=Exception("persistent failure"))
        payload = {"message_id": "m1", "store_id": 7}
        fields = {b"payload": json.dumps(payload).encode(), b"retries": b"3"}  # == MAX_RETRIES

        await message_queue._process_entry(mock_r, b"123-0", fields, "w0", handler)

        handler.assert_not_awaited()  # pas appelé si max retries dépassé
        # La DLQ doit être alimentée
        calls = [str(c) for c in mock_r.xadd.call_args_list]
        assert any("dlq" in c.lower() for c in calls) or mock_r.xadd.await_count >= 1

    @pytest.mark.asyncio
    async def test_acknowledges_on_success(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        handler = AsyncMock()
        fields = {b"payload": b'{"store_id": 1}', b"retries": b"0"}
        await message_queue._process_entry(mock_r, b"1-0", fields, "w0", handler)
        mock_r.xack.assert_awaited_once()


class TestGetQueueStats:

    @pytest.mark.asyncio
    async def test_returns_stats_dict(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        mock_r.xlen = AsyncMock(return_value=42)
        mock_r.exists = AsyncMock(return_value=1)
        mock_r.xpending = AsyncMock(return_value={"pending": 5})
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            stats = await message_queue.get_queue_stats()
        assert stats["stream_length"] == 42
        assert "dlq_length" in stats
        assert "pending_count" in stats

    @pytest.mark.asyncio
    async def test_returns_error_if_redis_unavailable(self):
        from services import message_queue
        with patch.object(message_queue, "_get_redis", return_value=None):
            stats = await message_queue.get_queue_stats()
        assert "error" in stats

    @pytest.mark.asyncio
    async def test_handles_redis_exception(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        mock_r.xlen.side_effect = Exception("Redis error")
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            stats = await message_queue.get_queue_stats()
        assert "error" in stats


class TestWebhookDecouplingContract:
    """Vérifie le contrat de découplage : webhook -> queue -> worker IA."""

    def test_push_message_is_async(self):
        import asyncio

        from services.message_queue import push_message
        assert asyncio.iscoroutinefunction(push_message)

    def test_consume_messages_is_async(self):
        import asyncio

        from services.message_queue import consume_messages
        assert asyncio.iscoroutinefunction(consume_messages)

    def test_get_queue_stats_is_async(self):
        import asyncio

        from services.message_queue import get_queue_stats
        assert asyncio.iscoroutinefunction(get_queue_stats)

    def test_stream_constants_defined(self):
        from services.message_queue import _CONSUMER_GROUP, _DLQ_STREAM, _STREAM_NAME
        assert _STREAM_NAME.startswith("wa:")
        assert "dlq" in _DLQ_STREAM.lower()
        assert _CONSUMER_GROUP

    def test_max_retries_is_positive(self):
        from services.message_queue import _MAX_RETRIES
        assert _MAX_RETRIES > 0

    @pytest.mark.asyncio
    async def test_push_message_idempotent_on_empty_payload(self):
        from services import message_queue
        mock_r = _make_mock_redis()
        with patch.object(message_queue, "_get_redis", return_value=mock_r):
            # Payload minimal sans message_id -> pas de déduplication, mais pas de crash
            result = await message_queue.push_message({})
        # Doit retourner une valeur ou None, sans lever d'exception
        assert result is None or isinstance(result, str)
