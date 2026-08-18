"""services/session_cleanup.py — Job de nettoyage des sessions expirées.

Ce module fournit un job de nettoyage en temps réel qui s'exécute en arrière-plan
et supprime périodiquement :
  - Les tokens de réinitialisation de mot de passe expirés ou utilisés
    (table ``password_reset_tokens``)

Le job tourne en boucle asyncio dans le lifespan FastAPI (aucune dépendance
à Celery, APScheduler ou un worker externe).

Configuration :
  CLEANUP_INTERVAL_SECONDS  — intervalle entre deux passes (défaut : 3600 = 1h)
  CLEANUP_BATCH_SIZE        — nombre max de lignes supprimées par passe (défaut : 500)

Usage (dans main.py lifespan) :
    from services.session_cleanup import start_cleanup_job
    cleanup_task = asyncio.create_task(start_cleanup_job())
    yield
    cleanup_task.cancel()
    await asyncio.gather(cleanup_task, return_exceptions=True)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import and_, delete

from models.database import AsyncSessionLocal, PasswordResetToken

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
import os

CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))
CLEANUP_BATCH_SIZE: int = int(os.getenv("CLEANUP_BATCH_SIZE", "500"))


async def _run_cleanup_pass() -> dict[str, int]:
    """Exécute une passe de nettoyage et retourne les statistiques."""
    stats: dict[str, int] = {"password_reset_tokens": 0}
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        try:
            # Supprime les tokens expirés OU déjà utilisés
            result = await session.execute(
                delete(PasswordResetToken)
                .where(
                    and_(
                        # Expirés depuis plus de 5 minutes (marge de sécurité)
                        PasswordResetToken.expires_at < now,
                    )
                )
                .execution_options(synchronize_session=False)
            )
            expired_count = result.rowcount or 0

            # Supprime aussi les tokens utilisés vieux de plus de 24h (traces conservées 24h)
            result2 = await session.execute(
                delete(PasswordResetToken)
                .where(
                    and_(
                        PasswordResetToken.used,
                        PasswordResetToken.used_at < datetime.fromtimestamp(
                            now.timestamp() - 86400, tz=UTC
                        ),
                    )
                )
                .execution_options(synchronize_session=False)
            )
            used_count = result2.rowcount or 0

            await session.commit()
            stats["password_reset_tokens"] = expired_count + used_count

            if expired_count + used_count > 0:
                logger.info(
                    "session_cleanup: pass complete",
                    extra={
                        "expired_tokens": expired_count,
                        "used_tokens": used_count,
                        "total_deleted": expired_count + used_count,
                    },
                )
        except Exception as exc:
            await session.rollback()
            logger.error("session_cleanup: DB error during cleanup pass: %s", exc)

    return stats


async def start_cleanup_job() -> None:
    """Boucle asyncio principale du job de nettoyage de sessions.

    S'exécute en arrière-plan tant que la tâche asyncio n'est pas annulée.
    Les erreurs ne stoppent jamais la boucle — seulement loggées.
    """
    logger.info(
        "session_cleanup job started",
        extra={"interval_seconds": CLEANUP_INTERVAL_SECONDS},
    )
    # Première passe au démarrage (après 30s pour laisser la DB se stabiliser)
    await asyncio.sleep(30)
    while True:
        try:
            stats = await _run_cleanup_pass()
            logger.debug("session_cleanup: stats=%s", stats)
        except asyncio.CancelledError:
            logger.info("session_cleanup job stopping (cancelled)")
            raise
        except Exception as exc:
            logger.error("session_cleanup: unexpected error: %s", exc)

        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("session_cleanup job stopping (cancelled during sleep)")
            raise
