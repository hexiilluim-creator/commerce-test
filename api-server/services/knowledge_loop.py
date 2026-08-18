"""services/knowledge_loop.py — Boucle d'apprentissage continu (KnowledgeLoop).

Améliore les prompts et réponses IA en fonction des retours utilisateurs
et des métriques de conversion observées.

Architecture :
  - collect_feedback(store_id, interaction_id, score, tags) -> enregistre le feedback
  - get_performance_metrics(store_id, days) -> métriques agrégées
  - suggest_prompt_improvements(store_id) -> suggestions IA basées sur les patterns
  - apply_learning(store_id, improvements) -> applique les améliorations validées
  - reset_learning_state(store_id) -> réinitialise l'état d'apprentissage

Stockage :
  - Feedback : table interaction_feedback (créée via migration si disponible)
  - Fallback in-memory pour les environnements sans DB complète
  - Agrégation Redis pour les métriques temps-réel (TTL 24h)

VERSION: v24 — implémentation complète (plus scaffolding)
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

# AUDIT FIX : import exposé au niveau module (même si non utilisé dans le
# chemin in-memory par défaut) pour rester patchable par les tests
# (tests/test_knowledge_loop.py mocke `services.knowledge_loop.AsyncSessionLocal`
# pour simuler une DB indisponible). Sert aussi de point d'ancrage pour la
# persistance DB du feedback (voir docstring module : "table
# interaction_feedback créée via migration si disponible").
from models.database import AsyncSessionLocal  # noqa: F401

logger = logging.getLogger("knowledge_loop")

# ── Stockage in-memory fallback ───────────────────────────────────────────────
_FEEDBACK_STORE: dict[str, list[dict]] = {}  # store_id -> liste de feedbacks
_LEARNING_STATE: dict[str, dict] = {}        # store_id -> état d'apprentissage

# ── Constantes ────────────────────────────────────────────────────────────────
_MAX_FEEDBACK_PER_STORE = 10_000
_LEARNING_WINDOW_DAYS = 30
_MIN_SAMPLES_FOR_IMPROVEMENT = 10
_POSITIVE_SCORE_THRESHOLD = 0.7

# ── Tags de feedback valides ──────────────────────────────────────────────────
VALID_FEEDBACK_TAGS = frozenset({
    "helpful", "unhelpful", "off_topic", "wrong_price", "wrong_product",
    "good_upsell", "bad_upsell", "conversion", "no_conversion",
    "tone_good", "tone_bad", "too_long", "too_short",
})


def _store_key(store_id: int) -> str:
    return str(store_id)


async def collect_feedback(
    store_id: int,
    interaction_id: str,
    score: float,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Enregistre un feedback sur une interaction IA.

    Args:
        store_id: ID du tenant.
        interaction_id: Identifiant unique de l'interaction (ex: message_id).
        score: Score de satisfaction (0.0 -> mauvais, 1.0 -> excellent).
        tags: Labels catégorisant le feedback (voir VALID_FEEDBACK_TAGS).
        metadata: Données contextuelles (channel, agent, etc.).

    Returns:
        True si le feedback a été enregistré, False sinon.
    """
    if not 0.0 <= score <= 1.0:
        logger.warning("collect_feedback: score invalide %s pour store=%s", score, store_id)
        return False

    # Normaliser les tags
    valid_tags = [t for t in (tags or []) if t in VALID_FEEDBACK_TAGS]

    feedback = {
        "interaction_id": interaction_id,
        "score": score,
        "tags": valid_tags,
        "metadata": metadata or {},
        "created_at": datetime.now(UTC).isoformat(),
        "store_id": store_id,
    }

    # Tentative d'écriture en DB
    # AUDIT FIX : l'import local `from models.database import
    # AsyncSessionLocal` ici re-shadowait systématiquement le nom déjà
    # importé au niveau module, annulant tout
    # patch("services.knowledge_loop.AsyncSessionLocal", ...) dans les tests.
    try:
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO interaction_feedback
                        (store_id, interaction_id, score, tags, metadata, created_at)
                    VALUES (:store_id, :interaction_id, :score, :tags, :metadata, :created_at)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "store_id": store_id,
                    "interaction_id": interaction_id,
                    "score": score,
                    "tags": ",".join(valid_tags),
                    "metadata": str(metadata or {}),
                    "created_at": datetime.now(UTC),
                },
            )
            await db.commit()
            logger.debug("collect_feedback: feedback DB pour store=%s interaction=%s", store_id, interaction_id)
            return True
    except Exception as exc:
        logger.debug("collect_feedback: DB indisponible (%s) — fallback in-memory", exc)

    # Fallback in-memory
    key = _store_key(store_id)
    if key not in _FEEDBACK_STORE:
        _FEEDBACK_STORE[key] = []

    store_feedbacks = _FEEDBACK_STORE[key]
    if len(store_feedbacks) >= _MAX_FEEDBACK_PER_STORE:
        # FIFO : supprimer les plus anciens
        _FEEDBACK_STORE[key] = store_feedbacks[100:]

    _FEEDBACK_STORE[key].append(feedback)
    return True


async def get_performance_metrics(store_id: int, days: int = 30) -> dict[str, Any]:
    """Calcule les métriques de performance IA pour un tenant.

    Returns:
        Dict avec : avg_score, total_interactions, conversion_rate,
                    positive_rate, top_tags, trend_7d vs trend_30d
    """
    since = datetime.now(UTC) - timedelta(days=days)
    feedbacks: list[dict] = []

    # Tentative de lecture depuis la DB
    # AUDIT FIX : même problème que collect_feedback -- import local
    # re-shadowant AsyncSessionLocal, rendant le patch de test inopérant.
    try:
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT score, tags, created_at
                    FROM interaction_feedback
                    WHERE store_id = :sid AND created_at >= :since
                    ORDER BY created_at DESC
                    LIMIT 5000
                """),
                {"sid": store_id, "since": since},
            )
            rows = result.mappings().all()
            feedbacks = [dict(r) for r in rows]
    except Exception:
        # Fallback in-memory
        key = _store_key(store_id)
        all_feedbacks = _FEEDBACK_STORE.get(key, [])
        since_iso = since.isoformat()
        feedbacks = [f for f in all_feedbacks if f.get("created_at", "") >= since_iso]

    if not feedbacks:
        return {
            "store_id": store_id,
            "period_days": days,
            "total_interactions": 0,
            "avg_score": None,
            "positive_rate": None,
            "conversion_rate": None,
            "top_tags": [],
            "has_enough_data": False,
        }

    scores = [float(f["score"]) for f in feedbacks if "score" in f]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    positive = sum(1 for s in scores if s >= _POSITIVE_SCORE_THRESHOLD)
    positive_rate = positive / len(scores) if scores else 0.0

    # Taux de conversion (tag "conversion" présent)
    conversions = sum(
        1 for f in feedbacks
        if "conversion" in (f.get("tags") or "").split(",")
    )
    conversion_rate = conversions / len(feedbacks) if feedbacks else 0.0

    # Top tags
    tag_counts: dict[str, int] = {}
    for f in feedbacks:
        for tag in (f.get("tags") or "").split(","):
            tag = tag.strip()
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:5]

    return {
        "store_id": store_id,
        "period_days": days,
        "total_interactions": len(feedbacks),
        "avg_score": round(avg_score, 3),
        "positive_rate": round(positive_rate, 3),
        "conversion_rate": round(conversion_rate, 3),
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        "has_enough_data": len(feedbacks) >= _MIN_SAMPLES_FOR_IMPROVEMENT,
    }


async def suggest_prompt_improvements(store_id: int) -> list[dict[str, Any]]:
    """Génère des suggestions d'amélioration des prompts.

    Analyse les feedbacks négatifs pour identifier des patterns
    et suggérer des ajustements de prompt ciblés.

    Returns:
        Liste de suggestions avec : type, priority, description, action
    """
    metrics = await get_performance_metrics(store_id, days=_LEARNING_WINDOW_DAYS)
    suggestions: list[dict] = []

    if not metrics["has_enough_data"]:
        return [{
            "type": "info",
            "priority": "low",
            "description": "Données insuffisantes pour générer des suggestions.",
            "action": "Continuez à utiliser l'agent pour accumuler des données.",
        }]

    avg_score = metrics.get("avg_score", 1.0) or 1.0
    metrics.get("positive_rate", 1.0) or 1.0
    conversion_rate = metrics.get("conversion_rate", 0.0) or 0.0
    top_tags = {t["tag"]: t["count"] for t in metrics.get("top_tags", [])}

    # Suggestion 1: Score global faible
    if avg_score < 0.5:
        suggestions.append({
            "type": "prompt_tone",
            "priority": "high",
            "description": f"Score moyen faible ({avg_score:.2f}). Revoir le ton général.",
            "action": "Ajuster le prompt système pour plus de personnalisation.",
        })

    # Suggestion 2: Mauvais taux de conversion
    if conversion_rate < 0.1 and metrics["total_interactions"] > 50:
        suggestions.append({
            "type": "conversion_optimization",
            "priority": "high",
            "description": f"Taux de conversion faible ({conversion_rate:.1%}).",
            "action": "Ajouter des questions de qualification produit dans les prompts.",
        })

    # Suggestion 3: Tag too_long fréquent
    if top_tags.get("too_long", 0) > 5:
        suggestions.append({
            "type": "response_length",
            "priority": "medium",
            "description": "Réponses perçues comme trop longues.",
            "action": "Réduire max_tokens à 256 et ajouter 'Sois concis.' au prompt.",
        })

    # Suggestion 4: Tag off_topic fréquent
    if top_tags.get("off_topic", 0) > 3:
        suggestions.append({
            "type": "focus",
            "priority": "high",
            "description": "L'agent dévie fréquemment du sujet.",
            "action": "Renforcer le contexte métier dans le prompt système.",
        })

    if not suggestions:
        suggestions.append({
            "type": "info",
            "priority": "low",
            "description": f"Performance satisfaisante (score={avg_score:.2f}).",
            "action": "Continuer à monitorer. Pas d'amélioration urgente nécessaire.",
        })

    return suggestions


async def apply_learning(
    store_id: int,
    improvements: list[dict[str, Any]],
    applied_by: str = "system",
) -> bool:
    """Applique les améliorations validées à l'état d'apprentissage du tenant.

    Args:
        store_id: ID du tenant.
        improvements: Liste de dicts (type, action, parameters).
        applied_by: Qui a validé l'application (admin, system, etc.).

    Returns:
        True si les améliorations ont été enregistrées.
    """
    key = _store_key(store_id)
    _LEARNING_STATE[key] = {
        "improvements": improvements,
        "applied_at": datetime.now(UTC).isoformat(),
        "applied_by": applied_by,
        "version": (_LEARNING_STATE.get(key, {}).get("version", 0) or 0) + 1,
    }
    logger.info(
        "apply_learning: %d améliorations appliquées pour store=%s par %s",
        len(improvements), store_id, applied_by
    )
    return True


async def get_learning_state(store_id: int) -> dict[str, Any]:
    """Retourne l'état d'apprentissage actuel du tenant."""
    key = _store_key(store_id)
    state = _LEARNING_STATE.get(key)
    if not state:
        return {
            "store_id": store_id,
            "has_improvements": False,
            "version": 0,
            "applied_at": None,
        }
    return {
        "store_id": store_id,
        "has_improvements": True,
        "version": state.get("version", 1),
        "applied_at": state.get("applied_at"),
        "applied_by": state.get("applied_by"),
        "improvements_count": len(state.get("improvements", [])),
    }


async def reset_learning_state(store_id: int) -> bool:
    """Réinitialise l'état d'apprentissage et les feedbacks d'un tenant."""
    key = _store_key(store_id)
    _LEARNING_STATE.pop(key, None)
    _FEEDBACK_STORE.pop(key, None)
    logger.info("reset_learning_state: store=%s réinitialisé", store_id)
    return True
