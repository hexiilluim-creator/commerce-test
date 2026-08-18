"""services/lead_scoring.py — Lead Scoring IA Enterprise.

PHASE 1 — OMNICALL ENTERPRISE
Score: Cold | Warm | Hot

Critères :
  - budget (mention prix, montant)
  - urgence (délai, maintenant)
  - engagement (nb messages, interactions)
  - réponses (questions posées, boutons cliqués)
  - fréquence d'interaction (sessions, jours actifs)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class LeadScore(StrEnum):
    COLD = "cold"
    WARM = "warm"
    HOT  = "hot"


@dataclass
class LeadScoringResult:
    score_label: LeadScore
    score_value: int       # 0-100
    criteria: dict[str, int]
    explanation: str


# Poids des critères (total = 100)
_WEIGHTS = {
    "budget":    25,
    "urgency":   25,
    "engagement": 20,
    "responses": 15,
    "frequency": 15,
}

# Mots-clés budget
_BUDGET_KEYWORDS = [
    "combien", "prix", "tarif", "budget", "coût", "frais",
    "كم", "الثمن", "السعر", "بكاش",
]

# Mots-clés urgence
_URGENCY_KEYWORDS = [
    "urgent", "maintenant", "aujourd'hui", "vite", "besoin",
    "عاجل", "الآن", "اليوم", "باش نشري",
]


def _score_budget(conversation_text: str, last_messages: list[str]) -> int:
    """Score basé sur les mentions de prix/budget."""
    all_text = (conversation_text + " " + " ".join(last_messages)).lower()
    hits = sum(1 for kw in _BUDGET_KEYWORDS if kw in all_text)
    return min(hits * 33, 100)


def _score_urgency(conversation_text: str, emotion: str | None, last_messages: list[str]) -> int:
    """Score basé sur l'urgence détectée."""
    all_text = (conversation_text + " " + " ".join(last_messages)).lower()
    hits = sum(1 for kw in _URGENCY_KEYWORDS if kw in all_text)
    score = min(hits * 33, 75)
    if emotion == "urgent":
        score = min(score + 25, 100)
    return score


def _score_engagement(nb_messages: int, buttons_clicked: int) -> int:
    """Score basé sur le nombre de messages et interactions."""
    msg_score = min(nb_messages * 10, 60)
    btn_score = min(buttons_clicked * 20, 40)
    return min(msg_score + btn_score, 100)


def _score_responses(questions_asked: int, order_attempts: int) -> int:
    """Score basé sur les questions posées et tentatives de commande."""
    q_score = min(questions_asked * 20, 60)
    o_score = min(order_attempts * 40, 40)
    return min(q_score + o_score, 100)


def _score_frequency(nb_sessions: int, active_days: int) -> int:
    """Score basé sur la fréquence des interactions."""
    s_score = min(nb_sessions * 15, 60)
    d_score = min(active_days * 20, 40)
    return min(s_score + d_score, 100)


def compute_lead_score(
    conversation_text: str = "",
    last_messages: list[str] | None = None,
    emotion: str | None = None,
    nb_messages: int = 0,
    buttons_clicked: int = 0,
    questions_asked: int = 0,
    order_attempts: int = 0,
    nb_sessions: int = 1,
    active_days: int = 1,
) -> LeadScoringResult:
    """Calcule le score lead sur 100 et retourne Cold/Warm/Hot."""
    last_messages = last_messages or []

    c_budget    = _score_budget(conversation_text, last_messages)
    c_urgency   = _score_urgency(conversation_text, emotion, last_messages)
    c_engagement = _score_engagement(nb_messages, buttons_clicked)
    c_responses  = _score_responses(questions_asked, order_attempts)
    c_frequency  = _score_frequency(nb_sessions, active_days)

    criteria = {
        "budget":     c_budget,
        "urgency":    c_urgency,
        "engagement": c_engagement,
        "responses":  c_responses,
        "frequency":  c_frequency,
    }

    # Moyenne pondérée
    total = sum(
        criteria[k] * _WEIGHTS[k] / 100
        for k in _WEIGHTS
    )
    score_value = int(total)

    if score_value >= 65:
        label = LeadScore.HOT
        explanation = "Prospect très engagé — contacter en priorité."
    elif score_value >= 35:
        label = LeadScore.WARM
        explanation = "Prospect intéressé — nurturer avec une offre ciblée."
    else:
        label = LeadScore.COLD
        explanation = "Prospect froid — maintenir le contact sans pression."

    return LeadScoringResult(
        score_label=label,
        score_value=score_value,
        criteria=criteria,
        explanation=explanation,
    )


async def update_customer_lead_score(
    db,
    store_id: int,
    customer_id: int,
    result: LeadScoringResult,
) -> None:
    """Persiste le score lead dans la table customers (colonne lead_score)."""
    try:
        from sqlalchemy import text
        await db.execute(
            text("""
                UPDATE customers
                SET lead_score = :score,
                    lead_label = :label
                WHERE id = :cid AND store_id = :sid
            """),
            {
                "score": result.score_value,
                "label": result.score_label.value,
                "cid": customer_id,
                "sid": store_id,
            },
        )
    except Exception as exc:
        # Colonnes lead_score/lead_label ajoutées par migration 0034
        logger.warning("update_customer_lead_score failed: %s", exc)


async def get_hot_leads(db, store_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Retourne les prospects chauds (Hot) pour le dashboard commercial."""
    try:
        from sqlalchemy import text
        result = await db.execute(
            text("""
                SELECT c.id, c.whatsapp_phone, c.name, c.last_emotion,
                       c.lead_score, c.lead_label, c.last_message_at
                FROM customers c
                WHERE c.store_id = :sid
                  AND c.lead_label = 'hot'
                  AND c.opted_out = false
                ORDER BY c.lead_score DESC, c.last_message_at DESC
                LIMIT :lim
            """),
            {"sid": store_id, "lim": limit},
        )
        return [dict(r) for r in result.mappings().all()]
    except Exception as exc:
        logger.warning("get_hot_leads failed store=%s: %s", store_id, exc)
        return []
