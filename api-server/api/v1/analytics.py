"""
api/v1/analytics.py — Endpoints Analytics Complets (Dashboard V9)
==================================================================
  GET /api/v1/analytics/overview      -> KPIs globaux (CA, commandes, clients, msgs)
  GET /api/v1/analytics/sales         -> ventes par jour / mois
  GET /api/v1/analytics/channels      -> messages + clients par canal
  GET /api/v1/analytics/customers     -> clients potentiels, top clients, segments
  GET /api/v1/analytics/sentiment     -> distribution sentiment
  GET /api/v1/analytics/posts         -> vues/impressions posts réseaux sociaux
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import date_range as _range
from api.v1._deps import get_store_id as _sid
from models.database import (
    Appointment,
    AppointmentStatus,
    ConversationLog,
    Customer,
    Order,
    OrderStatus,
    get_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _pct(now, prev):
    if prev == 0:
        return 100 if now > 0 else 0
    return round(((now - prev) / prev) * 100, 1)


# ─── Overview ────────────────────────────────────────────────────────────────


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    sid = _sid()
    s30, _ = _range(30)
    s60, _ = _range(60)

    ca_now = float(
        await db.scalar(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.store_id == sid,
                Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED]),
                Order.created_at >= s30,
            )
        )
        or 0
    )
    ca_prev = float(
        await db.scalar(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.store_id == sid,
                Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED]),
                Order.created_at >= s60,
                Order.created_at < s30,
            )
        )
        or 0
    )
    orders_now = int(
        await db.scalar(select(func.count(Order.id)).where(Order.store_id == sid, Order.created_at >= s30)) or 0
    )
    orders_prev = int(
        await db.scalar(
            select(func.count(Order.id)).where(Order.store_id == sid, Order.created_at >= s60, Order.created_at < s30)
        )
        or 0
    )
    customers_total = int(await db.scalar(select(func.count(Customer.id)).where(Customer.store_id == sid)) or 0)
    customers_new = int(
        await db.scalar(select(func.count(Customer.id)).where(Customer.store_id == sid, Customer.created_at >= s30))
        or 0
    )
    messages_30d = int(
        await db.scalar(
            select(func.count(ConversationLog.id)).where(
                ConversationLog.store_id == sid, ConversationLog.created_at >= s30
            )
        )
        or 0
    )
    avg_order = ca_now / orders_now if orders_now > 0 else 0

    return {
        "period_days": 30,
        "revenue": ca_now,
        "revenue_details": {
            "current": ca_now,
            "previous": ca_prev,
            "change_pct": _pct(ca_now, ca_prev),
            "currency": "TND",
        },
        "orders": orders_now,
        "orders_details": {"current": orders_now, "previous": orders_prev, "change_pct": _pct(orders_now, orders_prev)},
        "customers": customers_total,
        "customers_details": {"total": customers_total, "new_30d": customers_new},
        "messages": messages_30d,
        "avg_order_value": round(avg_order, 3),
    }


# ─── Sales by day / month ────────────────────────────────────────────────────


@router.get("/sales")
async def get_sales(
    period: str = Query("30d", description="7d | 30d | 90d | 12m"),
    db: AsyncSession = Depends(get_db),
):
    sid = _sid()
    if period == "12m":
        start = datetime.now(UTC) - timedelta(days=365)
        result = await db.execute(
            select(
                func.date_trunc("month", Order.created_at).label("p"),
                func.count(Order.id).label("orders"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED]),
                                Order.total_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("revenue"),
            )
            .where(Order.store_id == sid, Order.created_at >= start)
            .group_by(literal_column("1"))  # BUG4 FIX: asyncpg GROUP BY position ref
            .order_by(literal_column("1"))
        )
        data = [
            {
                "period": r.p.strftime("%Y-%m"),
                "label": r.p.strftime("%b %Y"),
                "orders": int(r.orders),
                "revenue": float(r.revenue),
            }
            for r in result.fetchall()
        ]
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        start = datetime.now(UTC) - timedelta(days=days)
        result = await db.execute(
            select(
                func.date_trunc("day", Order.created_at).label("p"),
                func.count(Order.id).label("orders"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED]),
                                Order.total_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("revenue"),
            )
            .where(Order.store_id == sid, Order.created_at >= start)
            .group_by(literal_column("1"))  # BUG4 FIX: asyncpg GROUP BY position ref
            .order_by(literal_column("1"))
        )
        data = [
            {
                "period": r.p.strftime("%Y-%m-%d"),
                "label": r.p.strftime("%d %b"),
                "orders": int(r.orders),
                "revenue": float(r.revenue),
            }
            for r in result.fetchall()
        ]

    total_rev = sum(d["revenue"] for d in data)
    total_ord = sum(d["orders"] for d in data)
    return {
        "period": period,
        "data": data,
        "totals": {
            "revenue": total_rev,
            "orders": total_ord,
            "avg_order_value": round(total_rev / total_ord, 3) if total_ord else 0,
        },
    }


# ─── Messages par canal ──────────────────────────────────────────────────────


@router.get("/channels")
async def get_channel_stats(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    sid = _sid()
    start, _ = _range(days)
    result = await db.execute(
        select(
            ConversationLog.channel,
            func.count(ConversationLog.id).label("messages"),
            func.count(func.distinct(ConversationLog.customer_id)).label("customers"),
        )
        .where(ConversationLog.store_id == sid, ConversationLog.created_at >= start)
        .group_by(ConversationLog.channel)
    )
    rows = result.fetchall()
    ch_map = {r.channel: {"messages": int(r.messages), "customers": int(r.customers)} for r in rows}
    total = sum(d["messages"] for d in ch_map.values()) or 1
    META = {
        "whatsapp": {"icon": "💬", "color": "#25D366", "name": "WhatsApp"},
        "instagram": {"icon": "📸", "color": "#E1306C", "name": "Instagram"},
        "facebook": {"icon": "📘", "color": "#1877F2", "name": "Facebook"},
        "tiktok": {"icon": "🎵", "color": "#010101", "name": "TikTok"},
    }
    out = []
    for ch, meta in META.items():
        d = ch_map.get(ch, {"messages": 0, "customers": 0})
        out.append({**meta, "channel": ch, **d, "pct": round(d["messages"] / total * 100, 1)})
    out.sort(key=lambda x: x["messages"], reverse=True)
    return {"period_days": days, "total_messages": sum(d["messages"] for d in out), "channels": out}


# ─── Customers ───────────────────────────────────────────────────────────────


@router.get("/customers")
async def get_customer_analytics(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    sid = _sid()
    start, _ = _range(days)
    inactive_at = datetime.now(UTC) - timedelta(days=14)

    buyer_ids_res = await db.execute(
        select(Customer.id)
        .join(Order, Order.customer_id == Customer.id)
        .where(
            Customer.store_id == sid, Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED])
        )
        .distinct()
    )
    buyer_ids = {r[0] for r in buyer_ids_res.fetchall()}

    all_c = (await db.execute(select(Customer).where(Customer.store_id == sid))).scalars().all()
    prospects = [c for c in all_c if c.id not in buyer_ids]
    active = [c for c in all_c if c.last_message_at and c.last_message_at >= inactive_at]
    new_p = [c for c in all_c if c.created_at >= start]
    by_ch: dict = {}
    for c in all_c:
        by_ch[c.channel] = by_ch.get(c.channel, 0) + 1

    top_res = await db.execute(
        select(
            Customer.name,
            Customer.whatsapp_phone,
            Customer.channel,
            func.count(Order.id).label("n"),
            func.sum(Order.total_amount).label("total"),
        )
        .join(Order, Order.customer_id == Customer.id)
        .where(
            Customer.store_id == sid, Order.status.in_([OrderStatus.PAID, OrderStatus.DELIVERED, OrderStatus.SHIPPED])
        )
        .group_by(Customer.id, Customer.name, Customer.whatsapp_phone, Customer.channel)
        .order_by(func.sum(Order.total_amount).desc())
        .limit(5)
    )
    top = [
        {
            "name": r.name or r.whatsapp_phone,
            "channel": r.channel,
            "orders": int(r.n),
            "total_spent": float(r.total or 0),
        }
        for r in top_res.fetchall()
    ]

    return {
        "total": len(all_c),
        "buyers": len(buyer_ids),
        "prospects": len(prospects),
        "active_14d": len(active),
        "inactive": len(all_c) - len(active),
        "new_period": len(new_p),
        "by_channel": by_ch,
        "top_customers": top,
        "conversion_rate": round(len(buyer_ids) / len(all_c) * 100, 1) if all_c else 0,
    }


# ─── Sentiment ───────────────────────────────────────────────────────────────


@router.get("/sentiment")
async def get_sentiment(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    sid = _sid()
    start, _ = _range(days)
    total = int(
        await db.scalar(
            select(func.count(ConversationLog.id)).where(
                ConversationLog.store_id == sid, ConversationLog.created_at >= start
            )
        )
        or 0
    )

    rows = (
        await db.execute(
            select(ConversationLog.payload)
            .where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= start,
                ConversationLog.payload.isnot(None),
            )
            .limit(500)
        )
    ).fetchall()

    counts = {"positive": 0, "neutral": 0, "negative": 0, "urgent": 0}
    real = False
    for r in rows:
        s = (r.payload or {}).get("sentiment")
        if s in counts:
            counts[s] += 1
            real = True

    # P1.12-FIX (audit externe, juillet 2026) : cet endpoint remplaçait
    # silencieusement l'absence de données réelles par une distribution
    # inventée (72 % / 18 % / 7 % / 3 %) — un marchand voyait "72 % positif"
    # sans aucun moyen de savoir que ce chiffre ne mesurait rien. Le frontend
    # affichait même un disclaimer trompeur ("estimation basée sur les
    # transitions FSM") qui ne correspondait pas à ce que le code faisait
    # réellement. Ne plus jamais fabriquer de pourcentages : renvoyer une
    # distribution à zéro et laisser has_real_data=False piloter l'affichage
    # côté frontend (qui doit alors afficher un message honnête, pas un
    # graphique avec des chiffres inventés).

    tot = sum(counts.values()) or 1
    return {
        "period_days": days,
        "total_analyzed": total,
        "has_real_data": real,
        "distribution": {k: {"count": v, "pct": round(v / tot * 100, 1)} for k, v in counts.items()},
    }


# ─── Posts & vues réseaux sociaux ────────────────────────────────────────────


@router.get("/posts")
async def get_posts_analytics(db: AsyncSession = Depends(get_db)):
    """
    Métriques posts sociaux par canal.

    Source de données :
      - Compte les posts/messages réels du store dans `ConversationLog`
        agrégés par canal sur les 30 derniers jours.
      - Si la table `social_posts` existe (publication sortante BLOC 11),
        elle est priorisée pour les vraies métriques de vues/likes.

    Si aucun canal n'est configuré (pas de tokens BYOK + 0 conversation),
    retourne `{"configured": false, "channels": {}}` plutôt qu'un faux 200.
    """
    sid = _sid()
    since, _ = _range(30)

    # Comptage réel des messages entrants/sortants par canal
    rows = (
        await db.execute(
            select(ConversationLog.channel, func.count(ConversationLog.id))
            .where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= since,
            )
            .group_by(ConversationLog.channel)
        )
    ).all()

    by_channel: dict[str, dict] = {}
    for channel, count in rows:
        if not channel:
            continue
        by_channel[channel] = {
            "messages_30d": int(count or 0),
            "insights_available": False,  # passera à True quand BLOC 11 publishera des vraies métriques
        }

    # Vérifie si BYOK est configuré pour ce store
    try:
        from models.database import Store  # type: ignore

        store = (await db.execute(select(Store).where(Store.id == sid))).scalar_one_or_none()
        configured = bool(
            store
            and (
                getattr(store, "instagram_token_enc", None)
                or getattr(store, "facebook_token_enc", None)
                or getattr(store, "tiktok_token_enc", None)
                or getattr(store, "whatsapp_access_token_enc", None)
            )
        )
    except Exception as _exc:
        logger.warning("operation failed: %s", _exc)
        configured = False

    return {
        "period_days": 30,
        "configured": configured,
        "channels": by_channel,
        "note": (
            "Insights détaillés (vues / likes / reach) seront enrichis automatiquement "
            "dès qu'un publisher sortant aura été activé pour ce store."
        ),
    }


# ── ACTION 5 : Emotion analytics ──────────────────────────────────────────────
@router.get("/emotion")
async def get_emotion_analytics(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    """ACTION 5 — Distribution émotions + clients nécessitant attention."""
    sid = _sid()
    start, _ = _range(days)
    result = await db.execute(
        select(Customer.last_emotion, func.count(Customer.id).label("count"))
        .where(Customer.store_id == sid, Customer.last_message_at >= start, Customer.last_emotion.isnot(None))
        .group_by(Customer.last_emotion)
    )
    dist = {r.last_emotion: int(r.count) for r in result.fetchall()}
    total = sum(dist.values()) or 1
    META = {
        "interested": {"label": "😊 Intéressé", "color": "#22c55e"},
        "hesitant": {"label": "🤔 Hésitant", "color": "#f59e0b"},
        "frustrated": {"label": "😤 Frustré", "color": "#f97316"},
        "urgent": {"label": "🚨 Urgent", "color": "#ef4444"},
    }
    emotion_data = [
        {"emotion": e, **m, "count": dist.get(e, 0), "pct": round(dist.get(e, 0) / total * 100, 1)}
        for e, m in META.items()
    ]
    attention = sum(dist.get(e, 0) for e in ("frustrated", "urgent"))
    at_res = await db.execute(
        select(Customer.id, Customer.whatsapp_phone, Customer.channel, Customer.last_message_at, Customer.last_emotion)
        .where(
            Customer.store_id == sid,
            Customer.last_emotion.in_(["frustrated", "urgent"]),
            Customer.last_message_at >= start,
        )
        .order_by(Customer.last_message_at.desc())
        .limit(10)
    )
    return {
        "period_days": days,
        "total_active": sum(dist.values()),
        "attention_needed": attention,
        "satisfaction_rate": round(dist.get("interested", 0) / total * 100, 1),
        "distribution": emotion_data,
        "attention_list": [
            {
                "customer_id": r.id,
                "phone": r.whatsapp_phone,
                "channel": r.channel,
                "emotion": r.last_emotion,
                "last_seen": r.last_message_at.isoformat() if r.last_message_at else None,
            }
            for r in at_res.fetchall()
        ],
    }


@router.get("/omnicall")
async def get_omnicall_analytics(days: int = Query(30), db: AsyncSession = Depends(get_db)):
    """KPI OmniCall orientés performance agent (multi-canal)."""
    sid = _sid()
    start, _ = _range(days)

    leads_captured = int(
        await db.scalar(
            select(func.count(func.distinct(ConversationLog.customer_id))).where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= start,
                ConversationLog.trigger == "lead_captured",
            )
        )
        or 0
    )

    inbound_total = int(
        await db.scalar(
            select(func.count(ConversationLog.id)).where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= start,
                ConversationLog.trigger == "omnicall_inbound",
            )
        )
        or 0
    )

    ai_response_total = int(
        await db.scalar(
            select(func.count(ConversationLog.id)).where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= start,
                ConversationLog.trigger == "omnicall_ai_response",
            )
        )
        or 0
    )

    human_transfer_total = int(
        await db.scalar(
            select(func.count(ConversationLog.id)).where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= start,
                ConversationLog.trigger == "human_transfer",
            )
        )
        or 0
    )

    appointments_total = int(
        await db.scalar(
            select(func.count(Appointment.id)).where(
                Appointment.store_id == sid,
                Appointment.created_at >= start,
                # La base audit contient status en VARCHAR alors que l'ORM
                # expose un SAEnum. Le cast explicite évite que asyncpg
                # n'envoie un paramètre de type appointmentstatus inexistant.
                Appointment.status.cast(String).in_([
                    AppointmentStatus.PENDING.value,
                    AppointmentStatus.CONFIRMED.value,
                    AppointmentStatus.COMPLETED.value,
                ]),
            )
        )
        or 0
    )

    rows = (
        await db.execute(
            select(ConversationLog.channel, ConversationLog.payload).where(
                ConversationLog.store_id == sid,
                ConversationLog.created_at >= start,
                ConversationLog.trigger.in_(["omnicall_ai_response", "human_transfer", "lead_captured"]),
                ConversationLog.payload.isnot(None),
            )
        )
    ).fetchall()

    latency_values: list[float] = []
    under_1s = 0
    context_values: list[int] = []
    intent_detected = 0
    catalog_attempts = 0
    catalog_successes = 0
    catalog_scores: list[float] = []
    negotiation_total = 0
    satisfaction_positive = 0
    satisfaction_negative = 0
    by_channel: dict[str, dict[str, int]] = {}

    for channel, payload in rows:
        data = payload or {}
        channel_stats = by_channel.setdefault(
            channel or "unknown", {"ai_responses": 0, "human_transfers": 0, "leads": 0}
        )
        event_type = data.get("event_type")
        if event_type == "ai_response":
            channel_stats["ai_responses"] += 1
            latency = data.get("response_latency_ms")
            if isinstance(latency, int | float):
                latency_values.append(float(latency))
                if float(latency) <= 1000:
                    under_1s += 1
            ctx = data.get("context_window_used")
            if isinstance(ctx, int):
                context_values.append(ctx)
            if data.get("intent_detected"):
                intent_detected += 1
            if data.get("catalog_attempted"):
                catalog_attempts += 1
                if (data.get("catalog_results") or 0) > 0:
                    catalog_successes += 1
                score = data.get("catalog_top_score")
                if isinstance(score, int | float):
                    catalog_scores.append(float(score))
            if data.get("negotiation_detected"):
                negotiation_total += 1
            if data.get("satisfaction_signal") == "positive":
                satisfaction_positive += 1
            elif data.get("satisfaction_signal") == "negative":
                satisfaction_negative += 1
        elif event_type == "human_transfer":
            channel_stats["human_transfers"] += 1
        elif event_type == "lead_captured":
            channel_stats["leads"] += 1

    avg_latency = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0.0
    avg_context = round(sum(context_values) / len(context_values), 1) if context_values else 0.0
    satisfaction_base = satisfaction_positive + satisfaction_negative

    return {
        "period_days": days,
        "targets": {
            "response_under_1s_pct": 95,
            "context_window_messages": 20,
            "intent_detection_pct": 95,
        },
        "kpis": {
            "leads_captured": leads_captured,
            "appointments_obtained": appointments_total,
            "ai_response_rate": round(ai_response_total / inbound_total * 100, 1) if inbound_total else 0.0,
            "human_transfer_rate": round(human_transfer_total / ai_response_total * 100, 1)
            if ai_response_total
            else 0.0,
            "satisfaction_rate": round(satisfaction_positive / satisfaction_base * 100, 1)
            if satisfaction_base
            else 0.0,
            "response_under_1s_rate": round(under_1s / len(latency_values) * 100, 1) if latency_values else 0.0,
            "avg_response_latency_ms": avg_latency,
            "avg_context_window_messages": avg_context,
            "intent_detection_proxy_rate": round(intent_detected / ai_response_total * 100, 1)
            if ai_response_total
            else 0.0,
            "catalog_reliability_rate": round(catalog_successes / catalog_attempts * 100, 1)
            if catalog_attempts
            else 0.0,
            "catalog_avg_top_score": round(sum(catalog_scores) / len(catalog_scores), 2) if catalog_scores else 0.0,
            "negotiation_rate": round(negotiation_total / ai_response_total * 100, 1) if ai_response_total else 0.0,
        },
        "volumes": {
            "inbound_messages": inbound_total,
            "ai_responses": ai_response_total,
            "human_transfers": human_transfer_total,
            "catalog_attempts": catalog_attempts,
            "catalog_successes": catalog_successes,
            "negotiations_detected": negotiation_total,
        },
        "by_channel": by_channel,
    }


# ─── Top products (CTO audit fix) ────────────────────────────────────────────
# Frontend Dashboard.jsx calls GET /analytics/top-products?limit=5 and expects
# items shaped { id, name, revenue, orders_count }. Order.items is a JSON
# column so we aggregate in Python — volume is bounded by the 30-day window.
@router.get("/top-products")
async def get_top_products(
    limit: int = Query(5, ge=1, le=50),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    sid = _sid()
    start, _end = _range(days)
    result = await db.execute(
        select(Order.items, Order.total_amount).where(
            Order.store_id == sid,
            Order.created_at >= start,
            Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DELIVERED]),
        )
    )
    rows = result.all()

    agg: dict[int, dict] = {}
    for items, _total in rows:
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            pid = it.get("product_id") or it.get("id")
            if pid is None:
                continue
            name = it.get("name") or f"Produit #{pid}"
            qty = int(it.get("qty", it.get("quantity", 1)) or 1)
            unit = float(it.get("unit_price", it.get("price", 0)) or 0)
            entry = agg.setdefault(pid, {"id": pid, "name": name, "orders_count": 0, "revenue": 0.0})
            entry["orders_count"] += qty
            entry["revenue"] += qty * unit
            # Keep latest seen name in case of variation
            entry["name"] = name

    top = sorted(agg.values(), key=lambda x: (x["orders_count"], x["revenue"]), reverse=True)[:limit]
    for t in top:
        t["revenue"] = round(t["revenue"], 3)
    return {"products": top, "period_days": days}
