from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from services import tasks


def test_retry_with_backoff_is_bounded_and_handles_negative_retries():
    with patch("services.metrics.celery_task_retries") as metric:
        assert tasks._retry_with_backoff("job", -1) == 1
        assert tasks._retry_with_backoff("job", 3) == 8
        assert tasks._retry_with_backoff("job", 20) == 120
    assert metric.labels.call_count == 3


def test_run_async_executes_coroutine_without_running_loop():
    async def value():
        return {"ok": True}

    assert tasks._run_async(value()) == {"ok": True}


@pytest.mark.asyncio
async def test_run_async_executes_coroutine_inside_running_loop():
    async def value():
        await asyncio.sleep(0)
        return 42

    assert tasks._run_async(value()) == 42


@pytest.mark.asyncio
async def test_run_async_propagates_worker_exception_inside_running_loop():
    async def failing():
        raise ValueError("expected")

    with pytest.raises(ValueError, match="expected"):
        tasks._run_async(failing())


@pytest.mark.asyncio
async def test_get_isolated_db_normalizes_postgres_url_and_disposes_engine():
    session = MagicMock()
    factory = MagicMock()
    context = MagicMock()
    context.__aenter__ = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=session)
    context.__aexit__ = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=None)
    factory.return_value = context
    engine = MagicMock()
    engine.dispose = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine) as create, patch(
        "sqlalchemy.ext.asyncio.async_sessionmaker", return_value=factory
    ), patch("config.settings", DATABASE_URL="postgresql://user:pass@db/app?sslmode=require&connect_timeout=4", DEBUG=False):
        values = [value async for value in tasks.get_isolated_db()]
    assert values == [session]
    assert create.call_args.args[0] == "postgresql+asyncpg://user:pass@db/app"
    engine.dispose.assert_awaited_once()


def test_stub_tasks_emit_alert_for_all_invocation_styles_when_celery_unavailable():
    if tasks._CELERY_AVAILABLE:
        pytest.skip("Celery is enabled in this environment")
    stub = tasks._TaskStub("unit-task")
    with patch.object(stub, "_alert") as alert:
        assert stub.delay(1, key="v") is None
        assert stub.apply_async(args=[1], kwargs={"x": 2}) is None
        assert stub(3) is None
    assert [call.args[0] for call in alert.call_args_list] == ["delay", "apply_async", "call"]
