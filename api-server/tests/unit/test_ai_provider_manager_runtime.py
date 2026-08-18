import time
from unittest.mock import patch

import pytest

from services import ai_provider_manager as manager


def test_provider_stats_failure_rate_and_serialization():
    stats = manager.ProviderStats("openai", requests=4, failures=1, last_used=10.0, last_failure=9.0)
    assert stats.failure_rate == 0.25
    payload = stats.to_dict()
    assert payload["name"] == "openai"
    assert payload["failure_rate"] == 0.25
    assert manager.ProviderStats("gemini").failure_rate == 0.0


def test_record_request_updates_success_and_failure(monkeypatch):
    manager._provider_stats.clear()
    with patch("services.ai_provider_manager.time.time", side_effect=[100.0, 101.0, 101.0]):
        manager.record_request("openai", True)
        manager.record_request("openai", False)
    stats = manager._provider_stats["openai"]
    assert stats.requests == 2
    assert stats.failures == 1
    assert stats.last_used == 101.0
    assert stats.last_failure == 101.0


@pytest.mark.asyncio
async def test_get_fallback_stats_includes_breaker_state():
    manager._provider_stats.clear()
    manager._provider_stats["openai"] = manager.ProviderStats("openai", requests=2, failures=1)
    manager._provider_stats["custom"] = manager.ProviderStats("custom")
    breaker = type("Breaker", (), {"state": "open"})()
    with patch("services.circuit_breaker._breakers", {"openai": breaker}):
        result = await manager.get_fallback_stats()
    by_name = {entry["name"]: entry for entry in result}
    assert by_name["openai"]["circuit_state"] == "open"
    assert by_name["custom"]["circuit_state"] == "closed"
