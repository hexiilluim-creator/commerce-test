"""services/emotion_detection.py — Moteur de Détection Émotionnelle Enterprise.

PHASE 1 — OMNICALL ENTERPRISE
Détecte les émotions dans les messages entrants et déclenche les alertes.

Émotions détectées :
  neutral | interested | hesitant | frustrated | angry | urgent

Flux :
  1. analyze_emotion(text) -> EmotionResult
  2. Si emotion critique -> déclencher alerte superviseur / escalade
  3. Stocker emotion_score + emotion_alert en DB / Redis
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

# AUDIT FIX : import remonté au niveau module (était local dans
# store_emotion_result). tests/test_emotion_detection.py mocke
# `services.emotion_detection.store_long_term`, ce qui échouait avec
# AttributeError tant que le nom n'existait qu'en local scope.
from services.conversation_memory_service import store_long_term  # noqa: F401

logger = logging.getLogger(__name__)

# Émotions reconnues
EMOTIONS = ["neutral", "interested", "hesitant", "frustrated", "angry", "urgent"]

# Émotions qui déclenchent une escalade automatique
ESCALATION_EMOTIONS = {"frustrated", "angry", "urgent"}

# Seuil de score pour alerte superviseur (0-100)
ALERT_SCORE_THRESHOLD = 70


@dataclass
class EmotionResult:
    emotion: str          = "neutral"
    score: int            = 0          # 0-100
    confidence: float     = 0.0        # 0.0-1.0
    triggers: list[str]   = field(default_factory=list)
    should_escalate: bool = False
    should_alert: bool    = False


# ── Détection heuristique rapide (sans LLM, < 1ms) ──────────────────────────

_HEURISTIC_RULES: dict[str, list[str]] = {
    "angry": [
        "remboursement", "arnaque", "scandaleux", "inacceptable",
        "jamais plus", "j'en ai marre", "honte", "catastrophe",
        "لازم ترجعلي", "محتال", "غش",
    ],
    "frustrated": [
        "toujours pas", "encore", "problème", "ça ne marche pas",
        "depuis hier", "depuis longtemps", "pas répondu",
        "ما عندكمش", "ما شريتش",
    ],
    "urgent": [
        "urgent", "maintenant", "aujourd'hui", "vite", "immédiatement",
        "besoin urgent", "tout de suite",
        "عاجل", "الآن", "اليوم",
    ],
    "hesitant": [
        "peut-être", "je sais pas", "je réfléchis", "pas sûr",
        "c'est cher", "trop cher", "comparer",
        "ما عرفتش", "باهي", "نشوف",
    ],
    "interested": [
        "je veux", "combien", "disponible", "livraison", "commander",
        "أريد", "بكم", "موجود",
    ],
}


def _heuristic_emotion(text: str) -> EmotionResult:
    """Détection rapide par règles lexicales (sans LLM)."""
    text_lower = text.lower()
    scores: dict[str, int] = {}
    triggers: dict[str, list[str]] = {}

    for emotion, keywords in _HEURISTIC_RULES.items():
        hits = [kw for kw in keywords if kw in text_lower]
        if hits:
            scores[emotion] = len(hits) * 25
            triggers[emotion] = hits

    if not scores:
        return EmotionResult(emotion="neutral", score=20, confidence=0.7)

    top_emotion = max(scores, key=lambda e: scores[e])
    score = min(scores[top_emotion], 100)

    return EmotionResult(
        emotion=top_emotion,
        score=score,
        confidence=0.75,
        triggers=triggers.get(top_emotion, []),
        should_escalate=top_emotion in ESCALATION_EMOTIONS and score >= 50,
        should_alert=score >= ALERT_SCORE_THRESHOLD,
    )


async def _llm_emotion(text: str, tenant_id: int | None = None) -> EmotionResult:
    """Détection fine via LLM (appelée pour les cas ambigus)."""
    import json

    from config import settings
    from services.llm_gateway import chat as llm_chat

    system = """Analyse l'émotion principale du message client.
Retourne UNIQUEMENT un JSON valide:
{"emotion":"neutral|interested|hesitant|frustrated|angry|urgent","score":0-100,"confidence":0.0-1.0,"triggers":["mot1"]}
score=0 (neutre calme) -> 100 (très intense).
emotion=angry si menace ou exige remboursement.
emotion=urgent si délai immédiat exigé."""

    try:
        r = await llm_chat(
            model=settings.OPENAI_LOW_COST_MODEL if hasattr(settings, "OPENAI_LOW_COST_MODEL") else "gpt-4o-mini",
            max_tokens=120,
            temperature=0.2,
            tenant_id=tenant_id,
            agent_name="emotion_detection",
            channel="internal",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text[:500]},
            ],
        )
        raw = r.choices[0].message.content.strip().replace("```json", "").replace("```", "")
        data = json.loads(raw)
        emotion = data.get("emotion", "neutral")
        if emotion not in EMOTIONS:
            emotion = "neutral"
        score = int(data.get("score", 0))
        return EmotionResult(
            emotion=emotion,
            score=score,
            confidence=float(data.get("confidence", 0.8)),
            triggers=data.get("triggers", []),
            should_escalate=emotion in ESCALATION_EMOTIONS and score >= 50,
            should_alert=score >= ALERT_SCORE_THRESHOLD,
        )
    except Exception as exc:
        logger.warning("_llm_emotion failed: %s", exc)
        return EmotionResult(emotion="neutral", score=20, confidence=0.5)


async def analyze_emotion(
    text: str,
    tenant_id: int | None = None,
    use_llm: bool = True,
) -> EmotionResult:
    """Point d'entrée principal — heuristique puis LLM si ambigu."""
    heuristic = _heuristic_emotion(text)

    # Si heuristique est confiante -> pas besoin du LLM (économie de tokens)
    if heuristic.confidence >= 0.75 and heuristic.emotion != "neutral":
        return heuristic

    if use_llm:
        return await _llm_emotion(text, tenant_id)

    return heuristic


async def store_emotion_result(
    db,
    store_id: int,
    customer_id: int,
    result: EmotionResult,
) -> None:
    """Persiste le résultat d'émotion dans Customer.last_emotion et conversation_memories."""
    try:
        from sqlalchemy import text, update

        from models.database import Customer
        # Mettre à jour last_emotion sur le Customer
        await db.execute(
            update(Customer)
            .where(Customer.id == customer_id, Customer.store_id == store_id)
            .values(last_emotion=result.emotion)
        )
        # Stocker en mémoire longue durée (store_long_term importé au niveau module)
        await store_long_term(
            db, store_id, customer_id,
            "emotion_event",
            {
                "emotion": result.emotion,
                "score": result.score,
                "confidence": result.confidence,
                "triggers": result.triggers,
                "should_escalate": result.should_escalate,
            },
        )
    except Exception as exc:
        logger.warning("store_emotion_result failed: %s", exc)


async def send_supervisor_alert(
    store_id: int,
    customer_id: int,
    customer_phone: str,
    result: EmotionResult,
) -> None:
    """Envoie une alerte superviseur (Redis pub/sub + log structuré)."""
    try:
        r = _get_redis()
        import json
        from datetime import UTC, datetime
        payload = json.dumps({
            "event": "emotion_alert",
            "store_id": store_id,
            "customer_id": customer_id,
            "customer_phone": customer_phone,
            "emotion": result.emotion,
            "score": result.score,
            "timestamp": datetime.now(UTC).isoformat(),
        }, ensure_ascii=False)
        await r.publish(f"alerts:store:{store_id}", payload)
        logger.warning(
            "EMOTION_ALERT store=%s customer=%s emotion=%s score=%s",
            store_id, customer_id, result.emotion, result.score,
        )
    except Exception as exc:
        logger.warning("send_supervisor_alert failed: %s", exc)


def _get_redis():
    from services.redis_lock import get_redis
    return get_redis()
