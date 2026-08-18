"""services/human_handoff_service.py — Service d'Escalade Humaine Enterprise.

PHASE 1 — OMNICALL ENTERPRISE
Déclenchement automatique si :
  - remboursement | litige | menace départ | insatisfaction élevée
  - angry/urgent détecté | score émotion > 70

Crée un enregistrement `human_handoffs` en DB.
Historise : raison escalade / temps résolution / agent concerné.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class HandoffReason(StrEnum):
    REFUND_REQUEST     = "refund_request"
    DISPUTE            = "dispute"
    CHURN_THREAT       = "churn_threat"
    HIGH_DISSATISFACTION = "high_dissatisfaction"
    ANGER_DETECTED     = "anger_detected"
    URGENCY_DETECTED   = "urgency_detected"
    MANUAL             = "manual"


# Mots-clés déclencheurs par raison
_TRIGGER_KEYWORDS: dict[HandoffReason, list[str]] = {
    HandoffReason.REFUND_REQUEST: [
        "remboursement", "rembourser", "restitution", "argent retour",
        "ارجع فلوسي", "رجع المبلغ",
    ],
    HandoffReason.DISPUTE: [
        "plainte", "litige", "tribunal", "huissier", "avocat",
        "arnaque", "fraude", "دعوى", "شكوى",
    ],
    HandoffReason.CHURN_THREAT: [
        "partir", "quitter", "annuler abonnement", "plus jamais",
        "concurrents", "متعاملش معاكم",
    ],
    HandoffReason.HIGH_DISSATISFACTION: [
        "très déçu", "très mécontent", "inacceptable", "scandaleux",
        "catastrophique", "نعسف", "مش راضي خالص",
    ],
}


def detect_handoff_triggers(text: str) -> list[HandoffReason]:
    """Détecte les déclencheurs d'escalade par analyse lexicale."""
    text_lower = text.lower()
    triggered = []
    for reason, keywords in _TRIGGER_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            triggered.append(reason)
    return triggered


async def should_escalate(
    text: str,
    emotion: str | None = None,
    emotion_score: int = 0,
) -> tuple[bool, list[HandoffReason]]:
    """Décide si une escalade est nécessaire.

    Returns (should_escalate: bool, reasons: list[HandoffReason])
    """
    reasons = detect_handoff_triggers(text)

    if emotion == "angry":
        reasons.append(HandoffReason.ANGER_DETECTED)
    if emotion == "urgent" and emotion_score >= 70:
        reasons.append(HandoffReason.URGENCY_DETECTED)

    # Dédupliquer
    reasons = list(dict.fromkeys(reasons))
    return bool(reasons), reasons


async def create_handoff(
    db,
    store_id: int,
    customer_id: int,
    customer_phone: str,
    reasons: list[HandoffReason],
    original_message: str = "",
    assigned_agent: str | None = None,
) -> dict[str, Any]:
    """Crée un enregistrement d'escalade humaine en DB."""
    try:
        import json

        from sqlalchemy import text
        now = datetime.now(UTC)
        result = await db.execute(
            text("""
                INSERT INTO human_handoffs
                    (store_id, customer_id, customer_phone, reasons, original_message,
                     assigned_agent, status, created_at)
                VALUES (:sid, :cid, :phone, :reasons::jsonb, :msg,
                        :agent, 'open', :now)
                RETURNING id
            """),
            {
                "sid": store_id,
                "cid": customer_id,
                "phone": customer_phone,
                "reasons": json.dumps([r.value for r in reasons], ensure_ascii=False),
                "msg": original_message[:500],
                "agent": assigned_agent,
                "now": now,
            },
        )
        handoff_id = result.scalar()
        logger.warning(
            "HUMAN_HANDOFF_CREATED id=%s store=%s customer=%s reasons=%s",
            handoff_id, store_id, customer_id, [r.value for r in reasons],
        )

        # Mettre à jour l'état FSM du customer -> WAITING_SUPPORT
        await db.execute(
            text("""
                UPDATE customers
                SET conversation_state = jsonb_set(
                    COALESCE(conversation_state, '{}'),
                    '{fsm_state}',
                    '"waiting_support"'
                )
                WHERE id = :cid AND store_id = :sid
            """),
            {"cid": customer_id, "sid": store_id},
        )

        # Notification Redis pub/sub
        await _publish_handoff_alert(store_id, handoff_id, customer_phone, reasons)

        return {"handoff_id": handoff_id, "status": "open", "reasons": [r.value for r in reasons]}
    except Exception as exc:
        logger.error("create_handoff failed store=%s customer=%s: %s", store_id, customer_id, exc)
        return {"handoff_id": None, "status": "error", "error": str(exc)}


async def resolve_handoff(
    db,
    handoff_id: int,
    store_id: int,
    agent_name: str,
    resolution_notes: str = "",
) -> bool:
    """Marque l'escalade comme résolue et historise le temps de résolution."""
    try:
        from sqlalchemy import text
        now = datetime.now(UTC)
        await db.execute(
            text("""
                UPDATE human_handoffs
                SET status = 'resolved',
                    resolved_at = :now,
                    resolution_notes = :notes,
                    assigned_agent = :agent,
                    resolution_time_minutes = EXTRACT(EPOCH FROM (:now - created_at)) / 60
                WHERE id = :hid AND store_id = :sid
            """),
            {"hid": handoff_id, "sid": store_id, "now": now, "notes": resolution_notes, "agent": agent_name},
        )
        logger.info("HUMAN_HANDOFF_RESOLVED id=%s agent=%s", handoff_id, agent_name)
        return True
    except Exception as exc:
        logger.error("resolve_handoff failed id=%s: %s", handoff_id, exc)
        return False


async def get_open_handoffs(db, store_id: int, limit: int = 50) -> list[dict]:
    """Liste les escalades ouvertes pour un store."""
    try:
        from sqlalchemy import text
        result = await db.execute(
            text("""
                SELECT id, customer_id, customer_phone, reasons,
                       original_message, assigned_agent, created_at
                FROM human_handoffs
                WHERE store_id = :sid AND status = 'open'
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"sid": store_id, "lim": limit},
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("get_open_handoffs failed store=%s: %s", store_id, exc)
        return []


async def _publish_handoff_alert(
    store_id: int,
    handoff_id: Any,
    customer_phone: str,
    reasons: list[HandoffReason],
) -> None:
    try:
        import json

        from services.redis_lock import get_redis
        r = get_redis()
        payload = json.dumps({
            "event": "human_handoff",
            "handoff_id": handoff_id,
            "store_id": store_id,
            "customer_phone": customer_phone,
            "reasons": [r.value for r in reasons],
        }, ensure_ascii=False)
        await r.publish(f"handoffs:store:{store_id}", payload)
    except Exception as exc:
        logger.warning("_publish_handoff_alert failed: %s", exc)
