from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.v1.dashboard_enterprise import ai_dashboard, ceo_dashboard, commercial_dashboard


def result_rows(rows):
    r = MagicMock()
    r.all.return_value = rows
    r.mappings.return_value.all.return_value = rows
    r.mappings.return_value.first.return_value = rows[0] if rows else None
    r.scalar.return_value = rows[0] if rows else 0
    return r


@pytest.mark.asyncio
async def test_ceo_dashboard_kpis_and_status_breakdown():
    db = AsyncMock()
    db.scalar.side_effect = [1000, 800, 900, 700, 10, 8, 20, 16, 9, 900, 2]
    db.execute.return_value = result_rows([("paid", 6), ("pending", 4)])
    with patch("api.v1.dashboard_enterprise._sid", return_value=11), patch("api.v1.dashboard_enterprise._range", return_value=("start", "end")):
        data = await ceo_dashboard(db, period_days=30)
    assert data["revenue"]["current"] == 1000.0
    assert data["revenue"]["change_pct"] == 25.0
    assert data["orders"]["current"] == 10
    assert data["conversion_rate_pct"] == 45.0
    assert data["appointments"] == 2
    assert data["avg_order_value_tnd"] == 100.0
    assert data["orders"]["by_status"]["paid"] == 6


@pytest.mark.asyncio
async def test_ai_dashboard_metrics_and_handoff_distribution():
    db = AsyncMock()
    db.scalar.side_effect = [100, 40, 10, 50]
    emo = result_rows([("happy", 30), (None, 20)])
    handoffs = MagicMock()
    handoffs.mappings.return_value.first.return_value = {"total": 8, "resolved": 6, "avg_min": 12.5}
    db.execute.side_effect = [emo, handoffs]
    with patch("api.v1.dashboard_enterprise._sid", return_value=11), patch("api.v1.dashboard_enterprise._range", return_value=("start", "end")):
        data = await ai_dashboard(db, period_days=30)
    assert data["conversations"]["total"] == 100
    assert data["conversations"]["resolution_rate_pct"] == 40.0
    assert data["satisfaction_score"] == 80.0
    assert data["emotions_distribution"]["neutral"] == 20
    assert data["human_handoffs"] == {"total": 8, "resolved": 6, "avg_resolution_minutes": 12.5}


@pytest.mark.asyncio
async def test_commercial_dashboard_pipeline_and_opportunities():
    db = AsyncMock()
    lead = result_rows([{"lead_label": "hot", "cnt": 3}, {"lead_label": "warm", "cnt": 2}, {"lead_label": "cold", "cnt": 1}])
    opportunity = MagicMock()
    opportunity.scalar.return_value = 2
    db.execute.side_effect = [lead, opportunity]
    db.scalar.side_effect = [125.0, 4]
    with patch("api.v1.dashboard_enterprise._sid", return_value=11), patch("api.v1.dashboard_enterprise._range", return_value=("start", "end")):
        data = await commercial_dashboard(db, period_days=30)
    assert data["leads"]["total"] == 6
    assert data["pipeline_value_tnd"] == 375.0
    assert data["recalls_suggested"] == 4
    assert data["opportunities"] == 2


@pytest.mark.asyncio
async def test_dashboard_zero_values_are_safe():
    db = AsyncMock()
    db.scalar.side_effect = [0] * 11
    db.execute.side_effect = [result_rows([]), result_rows([]), result_rows([])]
    with patch("api.v1.dashboard_enterprise._sid", return_value=11), patch("api.v1.dashboard_enterprise._range", return_value=("start", "end")):
        ceo = await ceo_dashboard(db, period_days=30)
    assert ceo["conversion_rate_pct"] == 0
    assert ceo["avg_order_value_tnd"] == 0.0
