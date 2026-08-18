import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import tasks


def test_retry_backoff_is_bounded():
    with patch("services.metrics.celery_task_retries", MagicMock()):
        assert tasks._retry_with_backoff("demo", 0) == 1
        assert tasks._retry_with_backoff("demo", 3) == 8
        assert tasks._retry_with_backoff("demo", 20) == 120


def test_run_async_without_running_loop():
    async def value():
        return 7
    assert tasks._run_async(value()) == 7


@pytest.mark.asyncio
async def test_run_async_inside_running_loop():
    async def value():
        return "ok"
    assert tasks._run_async(value()) == "ok"


from types import SimpleNamespace


async def _one_db(db):
    yield db


@pytest.mark.asyncio
async def test_reconcile_payment_handles_not_found_and_paid_without_broker():
    db = MagicMock()
    result = MagicMock(); result.scalar_one_or_none.return_value = None
    db.execute = pytest.helpers if False else None
    async def execute(stmt): return result
    db.execute = execute
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)):
        task_self = SimpleNamespace(name="reconcile_payment", request=SimpleNamespace(retries=0))
        assert tasks.reconcile_payment.run(99, "paymee") == {"status": "not_found"}

    link = SimpleNamespace(provider_config={}, provider_payment_id="PID", status="pending")
    result.scalar_one_or_none.return_value = link
    provider = AsyncMock(); provider.verify_payment.return_value = {"status": "paid"}
    db.commit = AsyncMock()
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)), patch("services.payment_factory.PaymentFactory.get", return_value=provider):
        response = tasks.reconcile_payment.run(1, "paymee")
    assert response == {"reconciled": True, "status": "paid"}
    assert link.status == "paid"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_order_notification_returns_not_found_then_success():
    db = MagicMock(); db.get = AsyncMock(return_value=SimpleNamespace(id=2))
    result = MagicMock(); result.scalar_one_or_none.return_value = None
    async def execute_missing(stmt): return result
    db.execute = execute_missing
    task_self = SimpleNamespace(name="send_order_notification", request=SimpleNamespace(retries=0))
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)):
        assert tasks.send_order_notification.run(7, 2, "paid") == {"notified": False, "reason": "order_not_found"}
    result.scalar_one_or_none.return_value = SimpleNamespace(id=7)
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)):
        response = tasks.send_order_notification.run(7, 2, "paid")
    assert response == {"notified": True, "order_id": 7, "event": "paid"}


def test_run_async_public_compatibility_alias_matches_internal_runner():
    assert tasks.run_async is tasks._run_async


@pytest.mark.asyncio
async def test_send_whatsapp_and_process_ai_wrappers_delegate_to_services():
    db = MagicMock()
    async def send_text(**kwargs): return {"sent": True, "phone": kwargs["phone"]}
    async def run_agent(**kwargs): return {"answer": "ok", "store_id": kwargs["store_id"]}
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)), patch("services.ai_agent.send_whatsapp_text", new=send_text):
        assert tasks.send_whatsapp_message.run("+216000", "Bonjour", 2) == {"sent": True, "phone": "+216000"}
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)), patch("services.structured_agent.run_agent", new=run_agent):
        assert tasks.process_ai_response.run(2, {"x": 1}) == {"answer": "ok", "store_id": 2}


def test_update_product_embedding_skips_in_memory_test_database():
    settings = SimpleNamespace(ENV="test", DATABASE_URL="sqlite+aiosqlite:///:memory:")
    with patch("config.settings", settings):
        result = tasks.update_product_embedding.run(4, 2)
    assert result == {"product_id": 4, "done": False, "skipped": "in_memory_test_db"}


@pytest.mark.asyncio
async def test_cleanup_orphaned_redis_sessions_delegates_and_returns_result():
    with patch("services.redis_session_cleanup.cleanup_orphaned_redis_sessions", new=AsyncMock(return_value={"deleted": 3})):
        assert tasks.cleanup_orphaned_redis_sessions.run() == {"deleted": 3}


@pytest.mark.asyncio
async def test_process_whatsapp_message_delegates_to_agent():
    db = MagicMock()
    async def handle(**kwargs):
        return {"handled": True, "store_id": kwargs["store_id"], "text": kwargs["message_text"]}
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)), patch("services.ai_agent.handle_whatsapp_message", new=handle):
        result = tasks.process_whatsapp_message.run(3, "+216111", "Salut")
    assert result == {"handled": True, "store_id": 3, "text": "Salut"}


@pytest.mark.asyncio
async def test_process_social_webhook_delegates_to_social_agent():
    db = MagicMock()
    async def handle(**kwargs):
        return {"handled": True, "platform": kwargs["platform"], "store_id": kwargs["store_id"]}
    payload = {"object": "instagram"}
    with patch("services.tasks.get_isolated_db", return_value=_one_db(db)), patch("services.social_agent.handle_social_event", new=handle):
        result = tasks.process_social_webhook.run("instagram", 4, payload)
    assert result == {"handled": True, "platform": "instagram", "store_id": 4}



def test_retry_backoff_tolerates_metrics_failure():
    broken = MagicMock()
    broken.labels.side_effect = RuntimeError("metrics unavailable")
    with patch("services.metrics.celery_task_retries", broken):
        assert tasks._retry_with_backoff("demo", 2) == 4


def test_run_async_propagates_coroutine_exception():
    async def broken():
        raise ValueError("boom")
    with pytest.raises(ValueError, match="boom"):
        tasks._run_async(broken())
