"""api/v1/omnicall_enterprise.py — Routes OmniCall Enterprise (Phase 1).

Routes :
  GET  /omnicall-enterprise/memory/{customer_id}        -> mémoire client
  GET  /omnicall-enterprise/handoffs                    -> escalades ouvertes
  POST /omnicall-enterprise/handoffs/{id}/resolve       -> résoudre escalade
  GET  /omnicall-enterprise/leads/hot                   -> prospects chauds
  GET  /omnicall-enterprise/emotions/alerts             -> alertes émotion
  GET  /omnicall-enterprise/summaries/{customer_id}     -> résumés conversation
  POST /omnicall-enterprise/analyze                     -> analyser message (émotion + lead)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1._deps import get_store_id as _sid
from models.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/omnicall-enterprise", tags=["OmniCall Enterprise"])


# ─── Schémas ─────────────────────────────────────────────────────────────────

class AnalyzeMessageRequest(BaseModel):
    customer_id: int
    customer_phone: str
    text: str
    use_llm: bool = True


class ResolveHandoffRequest(BaseModel):
    agent_name: str
    resolution_notes: str = ""


# ─── Mémoire client ───────────────────────────────────────────────────────────

@router.get("/memory/{customer_id}")
async def get_customer_memory(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Retourne la mémoire complète d'un client (court + long terme)."""
    sid = _sid()
    from services.conversation_memory_service import build_memory_context
    ctx = await build_memory_context(db, sid, customer_id)
    return {"customer_id": customer_id, "memory": ctx}


# ─── Escalades humaines ───────────────────────────────────────────────────────

@router.get("/handoffs")
async def list_open_handoffs(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=200),
):
    """Liste les escalades humaines ouvertes."""
    sid = _sid()
    from services.human_handoff_service import get_open_handoffs
    handoffs = await get_open_handoffs(db, sid, limit=limit)
    return {"handoffs": handoffs, "total": len(handoffs)}


@router.post("/handoffs/{handoff_id}/resolve")
async def resolve_handoff_endpoint(
    handoff_id: int,
    body: ResolveHandoffRequest,
    db: AsyncSession = Depends(get_db),
):
    """Marque une escalade comme résolue."""
    sid = _sid()
    from services.human_handoff_service import resolve_handoff
    ok = await resolve_handoff(db, handoff_id, sid, body.agent_name, body.resolution_notes)
    await db.commit()
    if not ok:
        raise HTTPException(status_code=404, detail="Escalade introuvable")
    return {"success": True, "handoff_id": handoff_id}


# ─── Lead Scoring ─────────────────────────────────────────────────────────────

@router.get("/leads/hot")
async def get_hot_leads(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=200),
):
    """Retourne les prospects chauds (Hot)."""
    sid = _sid()
    from services.lead_scoring import get_hot_leads
    leads = await get_hot_leads(db, sid, limit=limit)
    return {"leads": leads, "total": len(leads)}


# ─── Alertes émotionnelles ────────────────────────────────────────────────────

@router.get("/emotions/alerts")
async def get_emotion_alerts(
    db: AsyncSession = Depends(get_db),
    only_unacknowledged: bool = Query(True),
    limit: int = Query(50, le=200),
):
    """Liste les alertes émotionnelles."""
    sid = _sid()
    from sqlalchemy import text
    # SECURITY FIX: no f-string interpolation into SQL — use safe conditional
    try:
        if only_unacknowledged:
            result = await db.execute(
                text("""
                    SELECT id, customer_id, customer_phone, emotion, score,
                           message_excerpt, acknowledged, created_at
                    FROM emotion_alerts
                    WHERE store_id = :sid AND acknowledged = false
                    ORDER BY created_at DESC LIMIT :lim
                """),
                {"sid": sid, "lim": limit},
            )
        else:
            result = await db.execute(
                text("""
                    SELECT id, customer_id, customer_phone, emotion, score,
                           message_excerpt, acknowledged, created_at
                    FROM emotion_alerts
                    WHERE store_id = :sid
                    ORDER BY created_at DESC LIMIT :lim
                """),
                {"sid": sid, "lim": limit},
            )
        alerts = [dict(r) for r in result.mappings().all()]
    except Exception as exc:
        logger.warning("get_emotion_alerts failed: %s", exc)
        alerts = []
    return {"alerts": alerts, "total": len(alerts)}


# ─── Résumés conversation ─────────────────────────────────────────────────────

@router.get("/summaries/{customer_id}")
async def get_conversation_summaries(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, le=50),
):
    """Retourne les résumés de conversation d'un client."""
    sid = _sid()
    from sqlalchemy import text
    try:
        result = await db.execute(
            text("""
                SELECT summary_text, main_objection, next_actions, outcome,
                       emotion, emotion_score, lead_score, lead_label, created_at
                FROM conversation_summaries
                WHERE store_id = :sid AND customer_id = :cid
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"sid": sid, "cid": customer_id, "lim": limit},
        )
        summaries = [dict(r) for r in result.mappings().all()]
    except Exception as exc:
        logger.warning("get_conversation_summaries failed: %s", exc)
        summaries = []
    return {"customer_id": customer_id, "summaries": summaries}


# ─── Analyser message (diagnostic) ───────────────────────────────────────────

@router.post("/analyze")
async def analyze_message(
    body: AnalyzeMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Analyse un message : émotion + lead score + déclencheurs d'escalade."""
    sid = _sid()

    from services.emotion_detection import analyze_emotion, store_emotion_result
    from services.human_handoff_service import should_escalate
    from services.lead_scoring import compute_lead_score

    emotion_result = await analyze_emotion(body.text, tenant_id=sid, use_llm=body.use_llm)
    await store_emotion_result(db, sid, body.customer_id, emotion_result)

    escalate, reasons = await should_escalate(
        body.text, emotion_result.emotion, emotion_result.score
    )

    lead = compute_lead_score(
        conversation_text=body.text,
        emotion=emotion_result.emotion,
    )

    if escalate and reasons:
        from services.human_handoff_service import create_handoff
        handoff = await create_handoff(
            db, sid, body.customer_id, body.customer_phone, reasons, body.text
        )
    else:
        handoff = None

    await db.commit()

    return {
        "emotion": {
            "emotion": emotion_result.emotion,
            "score": emotion_result.score,
            "confidence": emotion_result.confidence,
            "triggers": emotion_result.triggers,
        },
        "lead": {
            "label": lead.score_label.value,
            "score": lead.score_value,
            "criteria": lead.criteria,
            "explanation": lead.explanation,
        },
        "escalation": {
            "should_escalate": escalate,
            "reasons": [r.value for r in reasons],
            "handoff": handoff,
        },
    }
