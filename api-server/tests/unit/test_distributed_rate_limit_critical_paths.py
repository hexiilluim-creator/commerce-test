from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import distributed_rate_limit as rl


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_in_test_environment(monkeypatch):
    monkeypatch.setenv("ENV", "test")
    result = await rl.check("auth.login", "client")
    assert result.allowed is True
    assert result.remaining == 999
    assert result.retry_after == 0


@pytest.mark.asyncio
async def test_rate_limit_sets_window_and_returns_remaining(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    pipe = MagicMock()
    pipe.execute.return_value = None
    pipe.execute = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=[2, -1])
    redis = MagicMock()
    redis.pipeline.return_value = pipe
    redis.expire = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
    with patch("services.redis_lock.get_redis", return_value=redis):
        result = await rl.check("auth.login", "client")
    assert result.allowed is True
    assert result.remaining == 8
    assert result.retry_after == 0
    redis.expire.assert_awaited_once_with("rl:auth.login:client", 60)


@pytest.mark.asyncio
async def test_rate_limit_rejects_after_maximum(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    pipe = MagicMock()
    pipe.execute = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=[11, 42])
    redis = MagicMock()
    redis.pipeline.return_value = pipe
    with patch("services.redis_lock.get_redis", return_value=redis):
        result = await rl.check("auth.login", "client")
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after == 42


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_raises(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with patch("services.redis_lock.get_redis", side_effect=RuntimeError("redis down")):
        result = await rl.check("auth.forgot_password", "client")
    assert result.allowed is True
    assert result.remaining == 3
    assert result.retry_after == 0


@pytest.mark.asyncio
async def test_rate_limit_uses_default_limits_for_unknown_key(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    pipe = MagicMock()
    pipe.execute = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=[1, 10])
    redis = MagicMock()
    redis.pipeline.return_value = pipe
    with patch("services.redis_lock.get_redis", return_value=redis):
        result = await rl.check("custom.endpoint", "client")
    assert result.allowed is True
    assert result.remaining == 99
