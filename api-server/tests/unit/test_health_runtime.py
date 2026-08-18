from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.v1 import health


def test_health_simple_live_and_version():
    assert health.health_simple.__name__ == "health_simple"
    assert health.health_live.__name__ == "health_live"


@pytest.mark.asyncio
async def test_health_component_helpers_without_external_services():
    with patch("api.v1.health._VERSION_FILE", SimpleNamespace(read_text=MagicMock(side_effect=OSError))):
        assert health._read_app_version() == "unknown"
    with patch("config.settings.OPENAI_API_KEY", "sk-test"):
        assert (await health._check_openai())["status"] == "configured"
    with patch("config.settings.OPENAI_API_KEY", "bad"):
        assert (await health._check_openai())["status"] == "misconfigured"

    with patch("services.circuit_breaker.list_breakers", return_value=[{"name": "stripe", "state": "open"}, {"name": "cash", "state": "closed"}]):
        result, degraded = await health._check_circuit_breakers()
    assert degraded is True and result["open_count"] == 1

    inspector = MagicMock()
    inspector.ping.return_value = {"worker@one": {"ok": "pong"}}
    fake_app = SimpleNamespace(control=SimpleNamespace(inspect=lambda timeout: inspector))
    with patch("services.celery_app.celery_app", fake_app):
        result, degraded = await health._check_celery_workers()
    assert result["status"] == "ok" and degraded is False


@pytest.mark.asyncio
async def test_health_queue_and_readiness_status_codes():
    redis = AsyncMock()
    redis.llen.side_effect = lambda key: 1 if key == "payments.dlq" else 0
    redis.aclose = AsyncMock()
    fake_redis = SimpleNamespace(from_url=lambda *args, **kwargs: redis)
    with patch.dict("sys.modules", {"redis": SimpleNamespace(asyncio=fake_redis)}), patch("config.settings.REDIS_URL", "redis://test"):
        result, degraded = await health._check_celery_queues()
    assert degraded is True and result["depths"]["payments.dlq"] == 1

    with patch("api.v1.health._check_database", new=AsyncMock(return_value={"status": "error"})), patch("api.v1.health._check_redis", new=AsyncMock(return_value={"status": "ok"})):
        response = await health.health_ready()
    assert response.status_code == 503
