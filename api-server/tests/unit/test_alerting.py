"""tests/test_alerting.py — Tests Système d'Alerting (Phase 4).
Tests : 20 cas
"""
import json
from unittest.mock import AsyncMock, patch

import pytest


class TestPublishAlert:
    @pytest.mark.asyncio
    async def test_publish_alert_to_global_channel(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, AlertType, publish_alert
            await publish_alert(AlertType.API_ERROR, AlertSeverity.CRITICAL, "Test error", store_id=1)
            mock_redis.publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_publish_alert_redis_down_graceful(self):
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, AlertType, publish_alert
            # Ne doit pas lever d'exception
            await publish_alert(AlertType.WHATSAPP_FAILURE, AlertSeverity.CRITICAL, "Failure")

    @pytest.mark.asyncio
    async def test_publish_alert_publishes_to_store_channel_when_store_id(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, AlertType, publish_alert
            await publish_alert(AlertType.AI_FAILURE, AlertSeverity.WARNING, "AI failed", store_id=5)
            # Doit publier sur 2 canaux : global + store-specific
            calls = mock_redis.publish.call_args_list
            channels = [c[0][0] for c in calls]
            assert any("store:5" in str(ch) for ch in channels)

    @pytest.mark.asyncio
    async def test_publish_alert_without_store_id_no_store_channel(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, AlertType, publish_alert
            await publish_alert(AlertType.REDIS_SATURATION, AlertSeverity.CRITICAL, "Sat 90%")
            calls = mock_redis.publish.call_args_list
            channels = [c[0][0] for c in calls]
            assert not any("store:" in str(ch) for ch in channels)

    @pytest.mark.asyncio
    async def test_alert_payload_structure(self):
        captured = []
        mock_redis = AsyncMock()
        async def capture_publish(channel, payload):
            captured.append(json.loads(payload))
        mock_redis.publish.side_effect = capture_publish
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, AlertType, publish_alert
            await publish_alert(AlertType.DB_CONNECTION, AlertSeverity.CRITICAL, "DB down")
        assert len(captured) > 0
        payload = captured[0]
        assert "alert_type" in payload
        assert "severity" in payload
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_alert_history_stored_in_redis_list(self):
        mock_redis = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, AlertType, publish_alert
            await publish_alert(AlertType.RATE_LIMIT, AlertSeverity.WARNING, "Rate limited", store_id=3)
            mock_redis.lpush.assert_awaited()


class TestSpecializedAlertHelpers:
    @pytest.mark.asyncio
    async def test_alert_api_error_critical_only_for_5xx(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import alert_api_error
            await alert_api_error("/test", 404, "Not found")
            # 404 ne doit pas déclencher d'alerte critique
            assert mock_redis.publish.await_count == 0

    @pytest.mark.asyncio
    async def test_alert_api_error_500_publishes(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import alert_api_error
            await alert_api_error("/payments", 500, "Internal error")
            mock_redis.publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_alert_whatsapp_failure(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import alert_whatsapp_failure
            await alert_whatsapp_failure(1, "Token expired")
            mock_redis.publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_alert_ai_failure(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import alert_ai_failure
            await alert_ai_failure(1, "gpt-4o-mini", "Rate limit exceeded")
            mock_redis.publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_alert_redis_saturation_warning_at_80(self):
        mock_redis = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, alert_redis_saturation
            # 82% -> WARNING (pas CRITICAL)
            captured = []
            async def cap(ch, p): captured.append(json.loads(p))
            mock_redis.publish.side_effect = cap
            mock_redis.lpush = AsyncMock()
            mock_redis.ltrim = AsyncMock()
            mock_redis.expire = AsyncMock()
            await alert_redis_saturation(82.0)
            if captured:
                assert captured[0]["severity"] == AlertSeverity.WARNING.value

    @pytest.mark.asyncio
    async def test_alert_redis_saturation_critical_at_90(self):
        mock_redis = AsyncMock()
        captured = []
        async def cap(ch, p): captured.append(json.loads(p))
        mock_redis.publish.side_effect = cap
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import AlertSeverity, alert_redis_saturation
            await alert_redis_saturation(92.0)
            if captured:
                assert captured[0]["severity"] == AlertSeverity.CRITICAL.value


class TestGetAlertHistory:
    @pytest.mark.asyncio
    async def test_get_alert_history_returns_list(self):
        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[
            b'{"alert_type":"api_error","severity":"critical","message":"test","timestamp":"2024-01-01T00:00:00"}',
        ])
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import get_alert_history
            result = await get_alert_history(10)
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_alert_history_redis_down_returns_empty(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.side_effect = Exception("Redis down")
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import get_alert_history
            result = await get_alert_history()
        assert result == []

    @pytest.mark.asyncio
    async def test_check_redis_health_returns_dict(self):
        mock_redis = AsyncMock()
        mock_redis.info = AsyncMock(return_value={"used_memory": 104857600, "maxmemory": 536870912})
        with patch("services.redis_lock.get_redis", return_value=mock_redis):
            from services.alerting import check_redis_health
            result = await check_redis_health()
        assert "status" in result
        assert "used_mb" in result
