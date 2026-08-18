"""api/v1/dashboard_enterprise.py — Dashboards Enterprise (Phase 2).

Routes :
  GET /dashboard-enterprise/ceo        -> Dashboard CEO (CA, commandes, leads, MRR)
  GET /dashboard-enterprise/ai         -> Dashboard IA (conversations, satisfaction, émotions)
  GET /dashboard-enterprise/commercial -> Dashboard Commercial (prospects, pipeline)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import date_range as _range
from api.v1._deps import get_store_id as _sid
from api.v1._deps import require_role
from models.database import (
    ConversationLog,
    Customer,
    Order,
    OrderStatus,
    get_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/dashboard-enterprise",
    tags=["Dashboard Enterprise"],
    dependencies=[require_role("admin")],  # CEO/AI/Commercial data — admin minimum
)


def _pct(now: float, prev: float) -> float:
    if prev == 0:
        return 100.0 if now > 0 else 0.0
    return round(((now - prev) / prev) * 100, 1)


# ─── Dashboard CEO ────────────────────────────────────────────────────────────

@router.get("/ceo")
async def ceo_dashboard(
    db: AsyncSession = Depends(get_db),
    period_days: int = Query(30, ge=7, le=365),
):
    """KPIs CEO : CA, commandes, leads, conversion, RDV, valeur moyenne, MRR."""
    sid = _sid()
    s_now, _ = _range(period_days)
    s_prev, _ = _range(period_days * 2)
    mrr_start, _ = _range(30)

    PAID_STATUSES = [OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED]

    # Run all independent scalar queries concurrently (REF-3: was 8 serial round-trips)
    (
        gross_now, gross_prev, paid_now, paid_prev, orders_now, orders_prev,
        leads_now, leads_prev, unique_customers_with_order, mrr
    ) = await asyncio.gather(
        db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.store_id == sid, Order.created_at >= s_now)),
        db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.store_id == sid,
                   Order.created_at >= s_prev, Order.created_at < s_now)),
        db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.store_id == sid, Order.status.in_(PAID_STATUSES), Order.created_at >= s_now)),
        db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.store_id == sid, Order.status.in_(PAID_STATUSES),
                   Order.created_at >= s_prev, Order.created_at < s_now)),
        db.scalar(select(func.count(Order.id))
            .where(Order.store_id == sid, Order.created_at >= s_now)),
        db.scalar(select(func.count(Order.id))
            .where(Order.store_id == sid, Order.created_at >= s_prev, Order.created_at < s_now)),
        db.scalar(select(func.count(Customer.id))
            .where(Customer.store_id == sid, Customer.created_at >= s_now)),
        db.scalar(select(func.count(Customer.id))
            .where(Customer.store_id == sid, Customer.created_at >= s_prev, Customer.created_at < s_now)),
        db.scalar(select(func.count(func.distinct(Order.customer_id)))
            .where(Order.store_id == sid, Order.status.in_(PAID_STATUSES), Order.created_at >= s_now)),
        db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0))
            .where(Order.store_id == sid, Order.status.in_(PAID_STATUSES), Order.created_at >= mrr_start)),
    )

    gross_now = float(gross_now or 0)
    gross_prev = float(gross_prev or 0)
    paid_now = float(paid_now or 0)
    paid_prev = float(paid_prev or 0)
    orders_now = int(orders_now or 0)
    orders_prev = int(orders_prev or 0)
    leads_now = int(leads_now or 0)
    leads_prev = int(leads_prev or 0)
    unique_customers_with_order = int(unique_customers_with_order or 0)
    mrr = float(mrr or 0)

    conversion_rate = round((unique_customers_with_order / leads_now * 100) if leads_now > 0 else 0, 1)
    # Panier moyen : CA brut / toutes les commandes, y compris non payées.
    avg_order = round(gross_now / orders_now, 3) if orders_now > 0 else 0.0

    rdv_count = 0
    try:
        from models.database import Appointment
        rdv_count = int(await db.scalar(
            select(func.count(Appointment.id))
            .where(Appointment.store_id == sid, Appointment.created_at >= s_now)
        ) or 0)
    except Exception as _exc:
        logger.warning("dashboard_enterprise.ceo rdv query failed: %s", _exc)

    status_breakdown: dict = {}
    try:
        status_result = await db.execute(
            select(Order.status, func.count(Order.id))
            .where(Order.store_id == sid, Order.created_at >= s_now)
            .group_by(Order.status)
        )
        status_breakdown = {str(s): c for s, c in status_result.all()}
    except Exception as _exc:
        logger.warning("dashboard_enterprise.ceo status_breakdown failed: %s", _exc)

    return {
        "period_days": period_days,
        "revenue": {
            "current": round(gross_now, 3),
            "previous": round(gross_prev, 3),
            "change_pct": _pct(gross_now, gross_prev),
            "gross_current_tnd": round(gross_now, 3),
            "gross_previous_tnd": round(gross_prev, 3),
            "paid_current_tnd": round(paid_now, 3),
            "paid_previous_tnd": round(paid_prev, 3),
            "currency": "TND",
        },
        "revenue_paid_tnd": round(paid_now, 3),
        "orders": {
            "current": orders_now,
            "previous": orders_prev,
            "change_pct": _pct(orders_now, orders_prev),
            "by_status": status_breakdown,
        },
        "leads": {
            "current": leads_now,
            "previous": leads_prev,
            "change_pct": _pct(leads_now, leads_prev),
        },
        "conversion_rate_pct": conversion_rate,
        "appointments": rdv_count,
        "avg_order_value_tnd": avg_order,
        "mrr_tnd": round(mrr, 3),
    }


# ─── Dashboard IA ─────────────────────────────────────────────────────────────

@router.get("/ai")
async def ai_dashboard(
    db: AsyncSession = Depends(get_db),
    period_days: int = Query(30, ge=7, le=365),
):
    """KPIs IA : conversations, satisfaction, émotions, taux résolution, escalades."""
    sid = _sid()
    s_now, _ = _range(period_days)

    # Run all independent scalar queries concurrently (REF-3b: was 5 serial round-trips)
    total_conversations, resolutions, neg_customers, total_customers = await asyncio.gather(
        db.scalar(select(func.count(ConversationLog.id))
            .where(ConversationLog.store_id == sid, ConversationLog.created_at >= s_now)),
        db.scalar(select(func.count(ConversationLog.id))
            .where(ConversationLog.store_id == sid, ConversationLog.to_state == "order_created",
                   ConversationLog.created_at >= s_now)),
        db.scalar(select(func.count(Customer.id))
            .where(Customer.store_id == sid, Customer.last_emotion.in_(["frustrated", "angry"]))),
        db.scalar(select(func.count(Customer.id)).where(Customer.store_id == sid)),
    )
    total_conversations = int(total_conversations or 0)
    resolutions        = int(resolutions or 0)
    neg_customers      = int(neg_customers or 0)
    total_customers    = int(total_customers or 0)

    resolution_rate    = round((resolutions / total_conversations * 100) if total_conversations > 0 else 0, 1)
    satisfaction_score = round((1 - neg_customers / total_customers) * 100, 1) if total_customers > 0 else 100.0

    # Distribution émotions (single GROUP BY — cannot be gathered with scalars)
    emotions_dist: dict = {}
    try:
        emo_result = await db.execute(
            select(Customer.last_emotion, func.count(Customer.id))
            .where(Customer.store_id == sid, Customer.last_emotion.isnot(None))
            .group_by(Customer.last_emotion)
        )
        emotions_dist = {(e or "neutral"): c for e, c in emo_result.all()}
    except Exception as _exc:
        logger.warning("ai_dashboard emotions_dist failed: %s", _exc)

    # Escalades humaines (single complex query)
    handoffs_total = 0
    handoffs_resolved = 0
    avg_resolution_min = 0.0
    try:
        result = await db.execute(
            text("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status='resolved') as resolved,
                       AVG(resolution_time_minutes) FILTER (WHERE status='resolved') as avg_min
                FROM human_handoffs
                WHERE store_id = :sid AND created_at >= :since
            """),
            {"sid": sid, "since": s_now},
        )
        row = result.mappings().first()
        if row:
            handoffs_total     = int(row["total"] or 0)
            handoffs_resolved  = int(row["resolved"] or 0)
            avg_resolution_min = round(float(row["avg_min"] or 0), 1)
    except Exception as exc:
        logger.debug("ai_dashboard handoffs query failed: %s", exc)

    return {
        "period_days": period_days,
        "conversations": {
            "total": total_conversations,
            "resolution_rate_pct": resolution_rate,
            "resolutions": resolutions,
        },
        "satisfaction_score": satisfaction_score,
        "emotions_distribution": emotions_dist,
        "human_handoffs": {
            "total": handoffs_total,
            "resolved": handoffs_resolved,
            "avg_resolution_minutes": avg_resolution_min,
        },
    }


# ─── Dashboard Commercial ─────────────────────────────────────────────────────

@router.get("/commercial")
async def commercial_dashboard(
    db: AsyncSession = Depends(get_db),
    period_days: int = Query(30, ge=7, le=365),
):
    """KPIs Commercial : prospects chauds, rappels, opportunités, pipeline."""
    sid = _sid()
    s_now, _ = _range(period_days)

    # Prospects par label
    lead_breakdown: dict = {}
    try:
        result = await db.execute(
            text("""
                SELECT lead_label, COUNT(*) as cnt
                FROM customers
                WHERE store_id = :sid AND lead_label IS NOT NULL
                GROUP BY lead_label
            """),
            {"sid": sid},
        )
        lead_breakdown = {r["lead_label"]: r["cnt"] for r in result.mappings().all()}
    except Exception as exc:
        logger.debug("commercial_dashboard lead_breakdown failed: %s", exc)

    hot_count  = lead_breakdown.get("hot", 0)
    warm_count = lead_breakdown.get("warm", 0)
    cold_count = lead_breakdown.get("cold", 0)

    # Rappels window
    recall_start = datetime.now(UTC) - timedelta(days=14)
    recall_end   = datetime.now(UTC) - timedelta(days=3)

    # Run avg_order + recalls concurrently (was 2 serial round-trips)
    avg_order_raw, recalls = await asyncio.gather(
        db.scalar(select(func.avg(Order.total_amount))
            .where(Order.store_id == sid, Order.created_at >= s_now)),
        db.scalar(select(func.count(Customer.id))
            .where(Customer.store_id == sid,
                   Customer.last_message_at >= recall_start,
                   Customer.last_message_at < recall_end,
                   Customer.opted_out.is_(False))),
    )
    avg_order_val  = float(avg_order_raw or 0)
    recalls        = int(recalls or 0)
    pipeline_value = round(avg_order_val * hot_count, 3)

    # Opportunités (hot leads sans commande dans la période)
    try:
        result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT c.id) as cnt
                FROM customers c
                WHERE c.store_id = :sid
                  AND c.lead_label = 'hot'
                  AND c.opted_out = false
                  AND NOT EXISTS (
                      SELECT 1 FROM orders o
                      WHERE o.customer_id = c.id
                        AND o.store_id = :sid
                        AND o.created_at >= :since
                  )
            """),
            {"sid": sid, "since": s_now},
        )
        opportunities = int(result.scalar() or 0)
    except Exception as _exc:
        logger.warning("commercial_dashboard opportunities failed: %s", _exc)
        opportunities = hot_count

    return {
        "period_days": period_days,
        "leads": {
            "hot": hot_count,
            "warm": warm_count,
            "cold": cold_count,
            "total": hot_count + warm_count + cold_count,
        },
        "pipeline_value_tnd": pipeline_value,
        "recalls_suggested": recalls,
        "opportunities": opportunities,
        "avg_order_value_tnd": round(avg_order_val, 3),
    }
