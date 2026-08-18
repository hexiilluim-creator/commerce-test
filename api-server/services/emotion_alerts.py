"""services/emotion_alerts.py — Alertes émotionnelles proactives (ACTION 4).

Déclenche des alertes (Slack, base de données) quand le score de frustration
d'un client dépasse le seuil configuré (EMOTION_ESCALATION_THRESHOLD).

Deux points d'entrée:
  - trigger_emotion_alert_if_needed(store_id, store_name, customer_id, emotion, db)
    → Incrémente le compteur de frustration et alerte si seuil atteint.
  - reset_frustration_counter(store_id, customer_id)
    → Remet à zéro après résolution (émotion positive).

Stockage: table emotion_alerts (créée en migration 0034_enterprise_omnicall.py).
Alertes Slack: SLACK_ALERT_WEBHOOK (optionnel).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Clé Redis pour le compteur de frustration par (store_id, customer_id)
_REDIS_KEY = "emotion:frustration:{store_id}:{customer_id}"
_COUNTER_TTL = 3600  # 1 heure — reset automatique si aucune interaction


async def _get_redis():
    """Connexion Redis lazy via le pool partagé."""
    try:
        from lib.redis_client import get_redis as _shared_get_redis
        return await _shared_get_redis()
    except Exception as exc:
        logger.warning("emotion_alerts: Redis unavailable — %s", exc)
        return None


async def _send_slack_alert(store_name: str, customer_id: int, emotion: str, count: int) -> None:
    """Envoie une alerte Slack si SLACK_ALERT_WEBHOOK est configuré."""
    webhook_url = os.environ.get("SLACK_ALERT_WEBHOOK", "")
    if not webhook_url:
        return

    message = {
        "text": (
            f":warning: *Alerte émotion — {store_name}*\n"
            f"Client #{customer_id} exprime `{emotion}` "
            f"pour la {count}e fois consécutive.\n"
            f"⏰ {datetime.now(UTC).strftime('%H:%M UTC')}"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=message)
            if resp.status_code not in (200, 204):
                logger.warning("Slack alert returned HTTP %s", resp.status_code)
            else:
                logger.info("emotion_alerts: Slack alert sent for customer %s", customer_id)
    except Exception as exc:
        # Ne jamais faire échouer le flux principal pour une alerte Slack
        logger.warning("emotion_alerts: Slack send failed — %s", exc)


async def _log_to_db(db, store_id: int, customer_id: int, emotion: str, escalated: bool) -> None:
    """Insère une ligne dans emotion_alerts (best-effort, ne bloque pas)."""
    try:
        from sqlalchemy import text
        await db.execute(
            text(
                "INSERT INTO emotion_alerts "
                "(store_id, customer_id, emotion, escalated, created_at) "
                "VALUES (:store_id, :customer_id, :emotion, :escalated, :created_at)"
            ),
            {
                "store_id": store_id,
                "customer_id": customer_id,
                "emotion": emotion,
                "escalated": escalated,
                "created_at": datetime.now(UTC),
            },
        )
    except Exception as exc:
        logger.warning("emotion_alerts: DB log failed — %s", exc)


async def trigger_emotion_alert_if_needed(
    store_id: int,
    store_name: str,
    customer_id: int,
    emotion: str,
    db=None,
) -> None:
    """Incrémente le compteur de frustration et déclenche une alerte si besoin.

    Args:
        store_id: ID de la boutique.
        store_name: Nom de la boutique (pour l'alerte Slack).
        customer_id: ID du client.
        emotion: Émotion détectée ("frustrated", "urgent", etc.).
        db: Session SQLAlchemy async (optionnelle — pour le log DB).
    """
    try:
        from config import settings
        threshold = settings.EMOTION_ESCALATION_THRESHOLD
    except Exception:
        threshold = int(os.environ.get("EMOTION_ESCALATION_THRESHOLD", "2"))

    r = await _get_redis()
    if r is None:
        # Sans Redis, on alerte directement (pas de dé-duplication)
        await _send_slack_alert(store_name, customer_id, emotion, 1)
        return

    key = _REDIS_KEY.format(store_id=store_id, customer_id=customer_id)
    try:
        count = await r.incr(key)
        await r.expire(key, _COUNTER_TTL)

        escalated = count >= threshold
        if escalated:
            logger.info(
                "emotion_alerts: threshold reached store=%s customer=%s emotion=%s count=%s",
                store_id, customer_id, emotion, count,
            )
            await _send_slack_alert(store_name, customer_id, emotion, count)

        if db is not None:
            await _log_to_db(db, store_id, customer_id, emotion, escalated)

    except Exception as exc:
        logger.warning("emotion_alerts: counter update failed — %s", exc)
    finally:
        await r.aclose()


async def reset_frustration_counter(store_id: int, customer_id: int) -> None:
    """Remet à zéro le compteur de frustration (émotion positive détectée).

    Appelé depuis structured_agent quand l'émotion passe à "satisfied" ou "happy".
    """
    r = await _get_redis()
    if r is None:
        return
    key = _REDIS_KEY.format(store_id=store_id, customer_id=customer_id)
    try:
        await r.delete(key)
        logger.debug("emotion_alerts: counter reset for customer %s", customer_id)
    except Exception as exc:
        logger.warning("emotion_alerts: reset failed — %s", exc)
    finally:
        await r.aclose()
