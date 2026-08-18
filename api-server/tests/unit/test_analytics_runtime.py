from unittest.mock import AsyncMock, patch

import pytest

from api.v1 import analytics


def test_pct_handles_zero_and_change():
    assert analytics._pct(10, 0) == 100
    assert analytics._pct(0, 0) == 0
    assert analytics._pct(110, 100) == 10.0
    assert analytics._pct(90, 100) == -10.0


@pytest.mark.asyncio
async def test_overview_computes_kpis_and_zero_average():
    db = AsyncMock()
    db.scalar.side_effect = [1000, 500, 0, 0, 12, 3, 7]
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_overview(db)
    assert result["revenue"] == 1000.0
    assert result["revenue_details"]["change_pct"] == 100.0
    assert result["orders"] == 0
    assert result["orders_details"]["change_pct"] == 0
    assert result["customers"] == 12
    assert result["customers_details"]["new_30d"] == 3
    assert result["avg_order_value"] == 0
    assert result["messages"] == 7


@pytest.mark.asyncio
async def test_sales_returns_daily_and_yearly_aggregates():
    from datetime import datetime, UTC
    db = AsyncMock()
    daily = type("Row", (), {"p": datetime(2026, 8, 14, tzinfo=UTC), "orders": 2, "revenue": 250})()
    yearly = type("Row", (), {"p": datetime(2026, 8, 1, tzinfo=UTC), "orders": 4, "revenue": 500})()
    db.execute.side_effect = [type("Result", (), {"fetchall": lambda self: [daily]})(), type("Result", (), {"fetchall": lambda self: [yearly]})()]
    with patch("api.v1.analytics._sid", return_value=9):
        result_day = await analytics.get_sales("7d", db)
        result_year = await analytics.get_sales("12m", db)
    assert result_day["totals"] == {"revenue": 250, "orders": 2, "avg_order_value": 125.0}
    assert result_year["data"][0]["period"] == "2026-08"


@pytest.mark.asyncio
async def test_channel_stats_returns_all_channels_sorted_and_percentages():
    db = AsyncMock()
    rows = [type("Row", (), {"channel": "whatsapp", "messages": 8, "customers": 3})(), type("Row", (), {"channel": "instagram", "messages": 2, "customers": 1})()]
    db.execute.return_value = type("Result", (), {"fetchall": lambda self: rows})()
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_channel_stats(7, db)
    assert result["total_messages"] == 10
    assert result["channels"][0]["channel"] == "whatsapp"
    assert result["channels"][0]["pct"] == 80.0
    assert len(result["channels"]) == 4


@pytest.mark.asyncio
async def test_customer_analytics_segments_customers_and_top_spenders():
    from datetime import datetime, timedelta, UTC
    db = AsyncMock()
    buyer_rows = [(1,)]
    customers = [
        type("Customer", (), {"id": 1, "name": "Buyer", "whatsapp_phone": "1", "channel": "whatsapp", "last_message_at": datetime.now(UTC), "created_at": datetime.now(UTC)})(),
        type("Customer", (), {"id": 2, "name": None, "whatsapp_phone": "2", "channel": "instagram", "last_message_at": datetime.now(UTC) - timedelta(days=30), "created_at": datetime.now(UTC)})(),
    ]
    top_rows = [type("Row", (), {"name": "Buyer", "whatsapp_phone": "1", "channel": "whatsapp", "n": 3, "total": 450})()]
    db.execute.side_effect = [
        type("Result", (), {"fetchall": lambda self: buyer_rows})(),
        type("Result", (), {"scalars": lambda self: type("Scalars", (), {"all": lambda self: customers})()})(),
        type("Result", (), {"fetchall": lambda self: top_rows})(),
    ]
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_customer_analytics(30, db)
    assert result["total"] == 2 and result["buyers"] == 1 and result["prospects"] == 1
    assert result["by_channel"] == {"whatsapp": 1, "instagram": 1}
    assert result["top_customers"][0]["total_spent"] == 450.0
    assert result["conversion_rate"] == 50.0


@pytest.mark.asyncio
async def test_sentiment_reports_real_distribution_and_zero_when_absent():
    db = AsyncMock()
    db.scalar.return_value = 3
    rows = [type("Row", (), {"payload": {"sentiment": "positive"}})(), type("Row", (), {"payload": {"sentiment": "negative"}})(), type("Row", (), {"payload": {}})()]
    db.execute.return_value = type("Result", (), {"fetchall": lambda self: rows})()
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_sentiment(7, db)
    assert result["has_real_data"] is True and result["distribution"]["positive"]["count"] == 1

    db.scalar.return_value = 0
    db.execute.return_value = type("Result", (), {"fetchall": lambda self: []})()
    with patch("api.v1.analytics._sid", return_value=9):
        empty = await analytics.get_sentiment(7, db)
    assert empty["has_real_data"] is False and all(v["count"] == 0 for v in empty["distribution"].values())


@pytest.mark.asyncio
async def test_posts_analytics_reports_channels_and_byok_configuration():
    db = AsyncMock()
    channel_result = type("Result", (), {"all": lambda self: [("whatsapp", 4), (None, 2)]})()
    store_result = type("Result", (), {"scalar_one_or_none": lambda self: type("Store", (), {"whatsapp_access_token_enc": "enc", "instagram_token_enc": None, "facebook_token_enc": None, "tiktok_token_enc": None})()})()
    db.execute.side_effect = [channel_result, store_result]
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_posts_analytics(db)
    assert result["configured"] is True and result["channels"]["whatsapp"]["messages_30d"] == 4


@pytest.mark.asyncio
async def test_emotion_analytics_computes_attention_and_serializes_list():
    db = AsyncMock()
    distribution = [type("Row", (), {"last_emotion": "interested", "count": 3})(), type("Row", (), {"last_emotion": "urgent", "count": 1})()]
    attention = [type("Row", (), {"id": 7, "whatsapp_phone": "216", "channel": "whatsapp", "last_emotion": "urgent", "last_message_at": None})()]
    db.execute.side_effect = [type("Result", (), {"fetchall": lambda self: distribution})(), type("Result", (), {"fetchall": lambda self: attention})()]
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_emotion_analytics(7, db)
    assert result["total_active"] == 4 and result["attention_needed"] == 1
    assert result["attention_list"][0]["emotion"] == "urgent"


@pytest.mark.asyncio
async def test_omnicall_analytics_computes_performance_kpis():
    rows = [
        ("whatsapp", {"event_type": "ai_response", "response_latency_ms": 800, "context_window_used": 10, "intent_detected": True, "catalog_attempted": True, "catalog_results": 2, "catalog_top_score": 0.9, "negotiation_detected": True, "satisfaction_signal": "positive"}),
        ("whatsapp", {"event_type": "ai_response", "response_latency_ms": 1500, "context_window_used": 20, "intent_detected": False, "catalog_attempted": True, "catalog_results": 0, "catalog_top_score": 0.4, "satisfaction_signal": "negative"}),
        ("instagram", {"event_type": "human_transfer"}),
        ("instagram", {"event_type": "lead_captured"}),
    ]
    db = AsyncMock()
    db.scalar.side_effect = [3, 5, 2, 1, 4]
    db.execute.return_value = type("Result", (), {"fetchall": lambda self: rows})()
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_omnicall_analytics(30, db)
    assert result["kpis"]["leads_captured"] == 3
    assert result["kpis"]["ai_response_rate"] == 40.0
    assert result["kpis"]["response_under_1s_rate"] == 50.0
    assert result["kpis"]["catalog_reliability_rate"] == 50.0
    assert result["volumes"]["human_transfers"] == 1
    assert result["by_channel"]["whatsapp"]["ai_responses"] == 2


@pytest.mark.asyncio
async def test_top_products_aggregates_valid_items_and_ignores_malformed_rows():
    db = AsyncMock()
    rows = [
        ([{"product_id": 1, "name": "A", "qty": 2, "unit_price": 10}, {"id": 2, "name": "B", "quantity": 1, "price": 8}], 28),
        ([{"product_id": 1, "name": "A2", "qty": 1, "unit_price": 10}, {"name": "missing"}], 10),
        (None, 0),
        ("not-a-list", 0),
    ]
    db.execute.return_value = type("Result", (), {"all": lambda self: rows})()
    with patch("api.v1.analytics._sid", return_value=9):
        result = await analytics.get_top_products(2, 30, db)
    assert result["period_days"] == 30
    assert result["products"][0] == {"id": 1, "name": "A2", "orders_count": 3, "revenue": 30.0}
    assert result["products"][1]["id"] == 2
