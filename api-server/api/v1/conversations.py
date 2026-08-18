"""api/v1/conversations.py — Conversation history + FSM log viewer (P1-C)"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.tenant import current_tenant_id
from models.database import ConversationLog, Customer, Order, WhatsAppMessage, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["Conversations"])


# ─── List customers with conversation stats ───────────────────────────────────
from api.v1._deps import get_store_id as _sid


@router.get("/")
async def list_conversations(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: str | None = None,
    channel: str | None = Query(None, description="whatsapp|instagram|facebook|tiktok"),
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    stmt = select(Customer).where(Customer.store_id == store_id)
    if q:
        stmt = stmt.where(
            Customer.whatsapp_phone.ilike(f"%{q}%") |
            Customer.name.ilike(f"%{q}%")
        )
    # Channel filter — social_agent stores channel on Customer.channel
    if channel and channel != "all":
        stmt = stmt.where(Customer.channel == channel)

    stmt = stmt.order_by(desc(Customer.last_message_at)).offset((page - 1) * limit).limit(limit)

    result = await db.execute(stmt)
    customers = result.scalars().all()

    count_stmt = select(func.count()).select_from(Customer).where(Customer.store_id == store_id)
    if channel and channel != "all":
        count_stmt = count_stmt.where(Customer.channel == channel)
    total = (await db.execute(count_stmt)).scalar()

    return {
        "items": [_serialize_customer(c) for c in customers],
        "total": total,
        "page": page,
    }


# ─── Get customer messages ────────────────────────────────────────────────────
@router.get("/{customer_id}/messages")
async def get_customer_messages(
    customer_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    cust_result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.store_id == store_id)
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(404, "Customer not found")

    msg_result = await db.execute(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.store_id == store_id, WhatsAppMessage.from_phone == customer.whatsapp_phone)
        .order_by(desc(WhatsAppMessage.created_at))
        .limit(limit)
    )
    messages = msg_result.scalars().all()

    return {
        "customer": _serialize_customer(customer),
        "messages": [_serialize_message(m) for m in reversed(messages)],
    }


# ─── Get FSM transition log ───────────────────────────────────────────────────
@router.get("/{customer_id}/fsm-log")
async def get_fsm_log(
    customer_id: int,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(
        select(ConversationLog)
        .where(ConversationLog.store_id == store_id, ConversationLog.customer_id == customer_id)
        .order_by(desc(ConversationLog.created_at))
        .limit(limit)
    )
    logs = result.scalars().all()

    return [
        {
            "id": log.id,
            "from_state": log.from_state,
            "to_state": log.to_state,
            "trigger": log.trigger,
            "order_id": log.order_id,
            "payload": log.payload,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# ─── Get customer orders ──────────────────────────────────────────────────────
@router.get("/{customer_id}/orders")
async def get_customer_orders(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")

    result = await db.execute(
        select(Order)
        .where(Order.store_id == store_id, Order.customer_id == customer_id)
        .order_by(desc(Order.created_at))
    )
    orders = result.scalars().all()

    return [
        {
            "id": o.id,
            "status": o.status,
            "total_amount": o.total_amount,
            "payment_provider": o.payment_provider,
            "items": o.items,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]


# ─── Serializers ──────────────────────────────────────────────────────────────
def _serialize_customer(c: Customer) -> dict:
    state = c.conversation_state or {}
    return {
        "id": c.id,
        "whatsapp_phone": c.whatsapp_phone,
        "name": c.name,
        "language": c.language,
        "fsm_state": state.get("fsm_state", "idle"),
        "last_emotion": c.last_emotion,
        "preferences": c.preferences,
        "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        # Social channel fields — populated by social_agent for IG/FB/TT customers
        "channel": getattr(c, "channel", None) or "whatsapp",
        "social_sender_id": getattr(c, "social_sender_id", None),
    }


def _serialize_message(m: WhatsAppMessage) -> dict:
    return {
        "id": m.id,
        "wa_message_id": m.wa_message_id,
        "message_type": m.message_type,
        "content": m.content,
        "ai_response": m.ai_response,
        "ai_analysis": m.ai_analysis,
        "processed": m.processed,
        "direction": getattr(m, "direction", "inbound"),
        "is_manual_reply": getattr(m, "is_manual_reply", False),  # amber bubble in UI
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# Handoff endpoint removed (out of scope for v20.2)


# ─── POST /{customer_id}/reply — manual reply in takeover mode ────────────────
from typing import Optional as _Optional

from pydantic import BaseModel as _BaseModel


class ManualReplyBody(_BaseModel):
    text: str
    channel: str | None = None  # override channel if needed


@router.post("/{customer_id}/reply")
async def send_manual_reply(
    customer_id: int,
    body: ManualReplyBody,
    db: AsyncSession = Depends(get_db),
):
    """
    Envoie une réponse manuelle à un client pendant une prise de main (takeover).

    Le texte est envoyé via le canal du client (WhatsApp / Instagram / Facebook / TikTok)
    et est loggé dans WhatsAppMessage avec is_manual_reply=True pour différencier
    les réponses manuelles des réponses IA dans l'UI.

    Pré-requis : le marchand doit avoir activé une prise de main via
    POST /whatsapp/agent/takeover/{phone} avant d'utiliser cet endpoint.
    L'endpoint fonctionne même sans takeover actif (pas de validation stricte)
    pour rester simple côté UX.
    """
    store_id = _sid()
    if not store_id:
        raise HTTPException(status_code=401, detail="No tenant context")

    # Load customer
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.store_id == store_id,
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Load store for ChannelRouter
    from models.database import Store
    store_result = await db.execute(select(Store).where(Store.id == store_id))
    store = store_result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Determine channel and recipient_id
    channel = body.channel or customer.channel or "whatsapp"
    if channel == "whatsapp":
        recipient_id = customer.whatsapp_phone
    else:
        recipient_id = customer.social_sender_id or customer.whatsapp_phone

    if not recipient_id:
        raise HTTPException(status_code=400, detail="No recipient_id for this customer")

    # Send via ChannelRouter (unified interface for WA/IG/FB/TT)
    try:
        from utils.channel_router import ChannelRouter
        router_client = ChannelRouter(store, channel=channel)
        if not router_client.is_configured:
            raise HTTPException(
                status_code=424,
                detail=f"Canal {channel} non configuré pour cette boutique",
            )
        await router_client.send_text(recipient_id, body.text)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "manual_reply failed store=%s customer=%s channel=%s: %s",
            store_id, customer_id, channel, e,
        )
        raise HTTPException(status_code=502, detail=f"Erreur lors de l'envoi via {channel}")

    # Log the manual reply in WhatsAppMessage
    msg = WhatsAppMessage(
        store_id=store_id,
        customer_id=customer_id,
        from_phone=recipient_id,
        direction="outbound",
        message_type="text",
        content=body.text,
        ai_response=body.text,
        is_manual_reply=True,
        processed=True,
    )
    db.add(msg)
    await db.commit()

    logger.info(
        "manual_reply sent store=%s customer=%s channel=%s len=%d",
        store_id, customer_id, channel, len(body.text),
    )

    return {
        "status": "sent",
        "channel": channel,
        "recipient": recipient_id[:6] + "***" if len(recipient_id) > 6 else recipient_id,
        "text_len": len(body.text),
    }
