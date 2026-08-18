"""services/alerting.py — Système d'Alerting Enterprise (Phase 4).

Détecte et publie des alertes pour :
  - erreurs critiques API
  - surcharge API (rate limit atteint)
  - saturation Redis
  - échec WhatsApp
  - échec IA (LLM)

Publish sur Redis pub/sub + log structlog.
Intégrable avec Prometheus AlertManager ou PagerDuty.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class AlertSeverity(StrEnum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class AlertType(StrEnum):
    API_ERROR        = "api_error"
    RATE_LIMIT       = "rate_limit"
    REDIS_SATURATION = "redis_saturation"
    WHATSAPP_FAILURE = "whatsapp_failure"
    AI_FAILURE       = "ai_failure"
    DB_CONNECTION    = "db_connection"
    BILLING_ANOMALY  = "billing_anomaly"
    TENANT_KILL_SWITCH = "tenant_kill_switch"


_ALERT_CHANNEL = "alerts:platform"
_ALERT_HISTORY_KEY = "alerts:history"
_ALERT_HISTORY_TTL = 86400 * 7  # 7 jours


async def publish_alert(
    alert_type: AlertType,
    severity: AlertSeverity,
    message: str,
    context: dict[str, Any] | None = None,
    store_id: int | None = None,
) -> None:
    """Publie une alerte sur Redis pub/sub et l'historise."""
    payload = {
        "alert_type": alert_type.value,
        "severity": severity.value,
        "message": message,
        "context": context or {},
        "store_id": store_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    level = {
        AlertSeverity.INFO: logger.info,
        AlertSeverity.WARNING: logger.warning,
        AlertSeverity.CRITICAL: logger.error,
    }.get(severity, logger.warning)

    level(
        "ALERT type=%s severity=%s store=%s msg=%s",
        alert_type.value, severity.value, store_id, message,
    )

    try:
        from services.redis_lock import get_redis
        r = get_redis()
        serialized = json.dumps(payload, ensure_ascii=False, default=str)

        # Publish sur le canal global
        await r.publish(_ALERT_CHANNEL, serialized)

        # Si store-specific -> publish aussi sur le canal store
        if store_id:
            await r.publish(f"alerts:store:{store_id}", serialized)

        # Historique rolling (liste Redis)
        await r.lpush(_ALERT_HISTORY_KEY, serialized)
        await r.ltrim(_ALERT_HISTORY_KEY, 0, 999)  # garder 1000 dernières alertes
        await r.expire(_ALERT_HISTORY_KEY, _ALERT_HISTORY_TTL)
    except Exception as exc:
        logger.warning("alerting publish failed (Redis unavailable): %s", exc)


async def get_alert_history(limit: int = 50) -> list[dict[str, Any]]:
    """Récupère l'historique des alertes depuis Redis."""
    try:
        from services.redis_lock import get_redis
        r = get_redis()
        raw_list = await r.lrange(_ALERT_HISTORY_KEY, 0, limit - 1)
        return [json.loads(item) for item in raw_list if item]
    except Exception as exc:
        logger.warning("get_alert_history failed: %s", exc)
        return []


# ── Helpers spécialisés ──────────────────────────────────────────────────────

async def alert_api_error(path: str, status_code: int, error: str, store_id: int | None = None) -> None:
    if status_code >= 500:
        await publish_alert(
            AlertType.API_ERROR, AlertSeverity.CRITICAL,
            f"HTTP {status_code} sur {path}: {error[:200]}",
            {"path": path, "status_code": status_code},
            store_id=store_id,
        )


async def alert_whatsapp_failure(store_id: int, error: str) -> None:
    await publish_alert(
        AlertType.WHATSAPP_FAILURE, AlertSeverity.CRITICAL,
        f"WhatsApp API échouée: {error[:200]}",
        {"error": error[:200]},
        store_id=store_id,
    )


async def alert_ai_failure(store_id: int | None, model: str, error: str) -> None:
    await publish_alert(
        AlertType.AI_FAILURE, AlertSeverity.WARNING,
        f"LLM {model} en échec: {error[:200]}",
        {"model": model, "error": error[:200]},
        store_id=store_id,
    )


async def alert_redis_saturation(used_memory_pct: float) -> None:
    severity = AlertSeverity.CRITICAL if used_memory_pct >= 90 else AlertSeverity.WARNING
    await publish_alert(
        AlertType.REDIS_SATURATION, severity,
        f"Redis memory usage: {used_memory_pct:.1f}%",
        {"used_memory_pct": used_memory_pct},
    )


async def alert_rate_limit(store_id: int, endpoint: str) -> None:
    await publish_alert(
        AlertType.RATE_LIMIT, AlertSeverity.WARNING,
        f"Rate limit atteint sur {endpoint}",
        {"endpoint": endpoint},
        store_id=store_id,
    )


async def check_redis_health() -> dict[str, Any]:
    """Vérifie la santé Redis et publie une alerte si nécessaire."""
    try:
        from services.redis_lock import get_redis
        r = get_redis()
        info = await r.info("memory")
        used_mb = int(info.get("used_memory", 0)) / 1024 / 1024
        max_mb_raw = info.get("maxmemory", 0)
        max_mb = int(max_mb_raw) / 1024 / 1024 if max_mb_raw else 0

        if max_mb > 0:
            pct = (used_mb / max_mb) * 100
            if pct >= 80:
                await alert_redis_saturation(pct)

        return {
            "status": "ok",
            "used_mb": round(used_mb, 1),
            "max_mb": round(max_mb, 1),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
