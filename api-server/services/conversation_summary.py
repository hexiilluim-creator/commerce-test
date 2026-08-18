"""services/conversation_summary.py — Résumé Automatique de Conversation.

PHASE 1 — OMNICALL ENTERPRISE
Génère après chaque conversation :
  - résumé
  - objection principale
  - prochaines actions
  - score émotion
  - score prospect
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


from config import settings
from services.llm_gateway import chat as llm_chat


async def generate_conversation_summary(
    messages: list[dict[str, str]],
    customer_name: str | None,
    emotion: str | None,
    emotion_score: int,
    lead_score: int,
    lead_label: str,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    """Génère un résumé structuré de la conversation via LLM.

    messages: [{"role":"user"|"assistant","content":"..."}]
    Retourne un dict stockable en JSON.
    """

    conversation_text = "\n".join(
        f"[{m['role'].upper()}] {m['content']}"
        for m in messages[-20:]  # derniers 20 messages max
    )

    system = """Analyse cette conversation client/agent et retourne UNIQUEMENT un JSON valide:
{
  "summary": "Résumé en 2-3 phrases de la conversation",
  "main_objection": "Objection principale du client ou null",
  "next_actions": ["action1", "action2"],
  "key_products_mentioned": ["produit1"],
  "outcome": "sale_completed|lead_captured|no_interest|escalated|pending"
}"""

    try:
        r = await llm_chat(
            model=settings.OPENAI_LOW_COST_MODEL if hasattr(settings, "OPENAI_LOW_COST_MODEL") else "gpt-4o-mini",
            max_tokens=400,
            temperature=0.3,
            tenant_id=tenant_id,
            agent_name="conversation_summary",
            channel="internal",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Conversation:\n{conversation_text}"},
            ],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("generate_conversation_summary LLM failed: %s", exc)
        data = {
            "summary": "Résumé non disponible",
            "main_objection": None,
            "next_actions": [],
            "key_products_mentioned": [],
            "outcome": "pending",
        }

    return {
        **data,
        "customer_name": customer_name,
        "emotion": emotion,
        "emotion_score": emotion_score,
        "lead_score": lead_score,
        "lead_label": lead_label,
        "generated_at": datetime.now(UTC).isoformat(),
    }


from services.conversation_memory_service import record_summary


async def save_summary(
    db,
    store_id: int,
    customer_id: int,
    summary: dict[str, Any],
) -> None:
    """Persiste le résumé dans conversation_memories et conversation_summaries."""
    try:
        # Stocker dans conversation_memories (mémoire long terme)
        await record_summary(db, store_id, customer_id, summary)

        # Stocker aussi dans conversation_summaries (table dédiée)
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO conversation_summaries
                    (store_id, customer_id, summary_text, main_objection,
                     next_actions, outcome, emotion, emotion_score,
                     lead_score, lead_label, created_at)
                VALUES (:sid, :cid, :summary, :objection,
                        :actions::jsonb, :outcome, :emotion, :emotion_score,
                        :lead_score, :lead_label, NOW())
            """),
            {
                "sid": store_id,
                "cid": customer_id,
                "summary": summary.get("summary", ""),
                "objection": summary.get("main_objection"),
                "actions": json.dumps(summary.get("next_actions", []), ensure_ascii=False),
                "outcome": summary.get("outcome", "pending"),
                "emotion": summary.get("emotion", "neutral"),
                "emotion_score": summary.get("emotion_score", 0),
                "lead_score": summary.get("lead_score", 0),
                "lead_label": summary.get("lead_label", "cold"),
            },
        )
    except Exception as exc:
        logger.warning("save_summary failed store=%s customer=%s: %s", store_id, customer_id, exc)
