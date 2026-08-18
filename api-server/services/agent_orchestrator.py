from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import BusinessConfig, BusinessType, Customer, Store

logger = logging.getLogger(__name__)

RouteRole = Literal["customer", "owner"]


@dataclass
class RouteDecision:
    route: str
    degraded_mode: bool
    reason: str


async def resolve_route(
    db: AsyncSession,
    *,
    store: Store,
    role: RouteRole,
    channel: str,
    billing_status: str | None,
    customer: Customer | None = None,
    text: str | None = None,
) -> RouteDecision:
    """Résout la route d'orchestration.

    FSM auto_fsm attendue:
      - auto_idle : conversation e-commerce générique, pas de session pièces auto active
      - auto_identification : identification véhicule / VIN / plaque
      - auto_search : recherche pièce / compatibilité
      - auto_quote : devis / disponibilité / panier
      - auto_handoff : transfert opérateur ou expertise atelier

    Règle clé: `auto_parts_mode` active seulement la route dédiée quand la FSM
    auto_fsm est sortie de `auto_idle`, ou quand le business_type du tenant est
    explicitement `AUTO_PARTS`.
    """
    if (billing_status or "active").lower() != "active":
        return RouteDecision(route="blocked", degraded_mode=True, reason="tenant_suspended")

    if role == "owner":
        return RouteDecision(route="owner_agent", degraded_mode=False, reason="owner_channel")

    business_type = None
    try:
        config = (
            await db.execute(select(BusinessConfig).where(BusinessConfig.store_id == store.id).limit(1))
        ).scalar_one_or_none()
        business_type = getattr(config, "business_type", None)
    except Exception as _exc:
        logger.warning("resolve_route failed: %s", _exc)
        business_type = None

    text_lower = (text or "").lower()
    # ── Mode pièces auto ──────────────────────────────────────────────────────
    if getattr(store, "auto_parts_mode", False):
        fsm_state = (customer.conversation_state or {}) if customer else {}
        auto_state = fsm_state.get("auto_fsm", "auto_idle")
        if auto_state != "auto_idle":
            logger.info("resolve_route", route="auto_parts_agent", reason="auto_parts_conversation", auto_state=auto_state)
            return RouteDecision(route="auto_parts_agent", degraded_mode=False, reason="auto_parts_conversation")

    rdv_keywords = {"rdv", "rendez-vous", "rendez vous", "réservation", "réserver", "appointment", "book", "موعد", "حجز"}
    appointment_hint = any(k in text_lower for k in rdv_keywords)

    if business_type == BusinessType.HYBRID or (isinstance(business_type, str) and business_type in ("auto", "auto_parts")):
        logger.info("resolve_route", route="auto_parts_agent", reason="business_type_auto_parts")
        return RouteDecision(route="auto_parts_agent", degraded_mode=False, reason="business_type_auto_parts")

    if business_type in {BusinessType.APPOINTMENTS, BusinessType.HYBRID}:
        apt_state = ((customer.conversation_state or {}) if customer else {}).get("apt_fsm", "apt_idle")
        if business_type == BusinessType.APPOINTMENTS or apt_state != "apt_idle" or appointment_hint:
            return RouteDecision(route="appointment_agent", degraded_mode=False, reason="business_type_appointments")

    if channel in {"instagram", "facebook", "tiktok"}:
        logger.info("resolve_route", route="social_sales_agent", reason="social_channel")
        return RouteDecision(route="social_sales_agent", degraded_mode=False, reason="social_channel")

    logger.info("resolve_route", route="commerce_agent", reason="default")
    return RouteDecision(route="commerce_agent", degraded_mode=False, reason="default")


async def dispatch_customer_message(
    db: AsyncSession,
    *,
    store: Store,
    customer: Customer,
    text: str,
    wa: object,
    channel: str = "whatsapp",
    payload: dict[str, object] | None = None,
) -> str:
    decision = await resolve_route(
        db,
        store=store,
        role="customer",
        channel=channel,
        billing_status=getattr(store, "billing_status", "active"),
        customer=customer,
        text=text,
    )
    if decision.route == "blocked":
        return "Le tenant est actuellement suspendu. Contactez la facturation pour réactivation."

    if decision.route == "auto_parts_agent":
        from services.auto_parts_agent import handle_auto_parts_message
        _payload = payload if payload else {"type": "text", "body": text}
        return await handle_auto_parts_message(db, store, customer, _payload, wa)

    if decision.route == "appointment_agent":
        from services.appointment_agent import handle_appointment_message

        return await handle_appointment_message(db, store, customer, text, wa)

    try:
        from services.structured_agent import handle_message as handle_structured_message
        return await handle_structured_message(db, store, customer, text, wa)
    except Exception as exc:
        # FIX C: was a silent WARNING — now ERROR with store context so ops
        # can detect which tenants are running degraded (on ai_agent V8 fallback)
        logger.error(
            "structured_agent.fallback store=%s customer=%s reason=%s — falling back to ai_agent V8",
            store.id, customer.id, exc,
            exc_info=True,
        )
        # V24 ENTERPRISE FIX: était un try block vide (import sans appel).
        # On alerte maintenant l'opérateur via emotion_alerts que cet agent
        # est en mode dégradé V8. Ce n'est pas une alerte émotion client —
        # c'est une alerte système ops (store owner) tracée dans les logs.
        try:
            from services.emotion_alerts import trigger_emotion_alert_if_needed
            await trigger_emotion_alert_if_needed(
                db=db,
                store=store,
                customer=customer,
                context={
                    "alert_type": "agent_degraded",
                    "fallback": "ai_agent_v8",
                    "reason": str(exc),
                    "store_id": store.id,
                },
            )
        except Exception as _alert_exc:
            # L'alerte est best-effort — ne pas bloquer le fallback V8
            logger.warning(
                "emotion_alert.dispatch_failed store=%s reason=%s",
                store.id, _alert_exc,
            )

        from services.ai_agent import handle_text_message
        return await handle_text_message(db, store, customer, text, wa)


async def dispatch_owner_message(db: AsyncSession, *, store: Store, text: str, wa: object, from_phone: str) -> str:
    from services.owner_agent import handle_owner_message

    return await handle_owner_message(db, store, text, wa, from_phone)


async def dispatch_social_message(
    *,
    store_id: int,
    channel: str,
    sender_id: str,
    message_text: str | None,
    message_type: str = "text",
    attachments: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    from services.social_agent import handle_social_message

    return await handle_social_message(
        store_id=store_id,
        channel=channel,
        sender_id=sender_id,
        message_text=message_text,
        message_type=message_type,
        attachments=attachments,
    )
