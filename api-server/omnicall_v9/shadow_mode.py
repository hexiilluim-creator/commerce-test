"""omnicall_v9/shadow_mode.py — Shadow Mode V9 + Observation.

HIGH-9 FIX — Budget guard shadow mode :
Budget global plateforme : 50 000 calls/mois
Budget par tenant : 500 calls/mois
Redis keys: omnicall_v9:shadow:global:{YYYY-MM}:calls
            omnicall_v9:shadow:{store_id}:{YYYY-MM}:calls

FIX v20.3 :
- run_shadow_v9() ne tente plus asyncio.get_running_loop() (risque RuntimeError
  en contexte sync dans les workers Celery).
- Deux modes d'exécution : async (FastAPI) et sync (Celery worker).
- Budget check synchrone pour usage en worker Celery.

VERSION: v24
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from omnicall_v9.flags.registry import should_run_v9_shadow
from omnicall_v9.normalizers.facebook import normalize_facebook_payload
from omnicall_v9.normalizers.instagram import normalize_instagram_payload
from omnicall_v9.normalizers.tiktok import normalize_tiktok_payload
from omnicall_v9.normalizers.whatsapp import normalize_whatsapp_payload
from omnicall_v9.observability.logger import log_pipeline_event
from omnicall_v9.pipeline.minimal import run_minimal_pipeline
from omnicall_v9.pipeline.safe_boundary import safe_process_unified

logger = logging.getLogger("omnicall_v9.shadow")

_SHADOW_GLOBAL_BUDGET_CALLS: int = 50_000
_SHADOW_PER_TENANT_MAX_CALLS: int = 500

_NORMALIZERS = {
    "whatsapp": normalize_whatsapp_payload,
    "instagram": normalize_instagram_payload,
    "facebook": normalize_facebook_payload,
    "tiktok": normalize_tiktok_payload,
}


def _get_redis_sync():
    """Retourne un client Redis synchrone ou None."""
    try:
        import os

        import redis as redis_lib
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        return redis_lib.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
    except Exception:
        return None


def _check_shadow_budget_sync(store_id: int | None) -> tuple[bool, str]:
    """Vérifie le budget shadow de manière synchrone (Celery-safe).

    VERSION FIX v20.3 : version synchrone pour usage en worker Celery.
    """
    try:
        r = _get_redis_sync()
        if not r:
            return True, "redis_unavailable_skip_budget"

        month_key = datetime.now(UTC).strftime("%Y-%m")
        global_key = f"omnicall_v9:shadow:global:{month_key}:calls"

        global_count = int(r.get(global_key) or 0)
        if global_count >= _SHADOW_GLOBAL_BUDGET_CALLS:
            return False, f"global_budget_exceeded:{global_count}/{_SHADOW_GLOBAL_BUDGET_CALLS}"

        if store_id:
            tenant_key = f"omnicall_v9:shadow:{store_id}:{month_key}:calls"
            tenant_count = int(r.get(tenant_key) or 0)
            if tenant_count >= _SHADOW_PER_TENANT_MAX_CALLS:
                return False, f"tenant_budget_exceeded:{tenant_count}/{_SHADOW_PER_TENANT_MAX_CALLS}"
            count = r.incr(tenant_key)
            if count == 1:
                r.expire(tenant_key, 31 * 24 * 3600)

        new_global = r.incr(global_key)
        if new_global == 1:
            r.expire(global_key, 31 * 24 * 3600)

        return True, "ok"

    except Exception as exc:
        logger.warning(
            "omnicall_v9.shadow.budget_check_error",
            extra={"store_id": store_id, "error": str(exc)},
        )
        return True, "budget_check_skipped"


def run_shadow_v9(payload: dict[str, object], channel: str, store_id: int | None = None) -> None:
    """Exécute V9 en shadow mode synchrone.

    FIX v20.3 : Exécution directement synchrone.
    Ancienne implémentation tentait asyncio.get_running_loop() — fragile
    en contexte Celery worker (pas de boucle asyncio active).

    Cette fonction est safe à appeler depuis :
    - FastAPI BackgroundTasks (exécutées dans le thread de l'event loop)
    - Celery workers (thread pool sync)
    """
    try:
        observer = None
        try:
            from omnicall_v9.observability.shadow_observer import get_shadow_observer
            observer = get_shadow_observer()
        except Exception:
            pass

        if not should_run_v9_shadow(store_id):
            return

        # Budget check synchrone (Celery-safe)
        allowed, budget_reason = _check_shadow_budget_sync(store_id)
        if not allowed:
            logger.info(
                "omnicall_v9.shadow.budget_skip",
                extra={"store_id": store_id, "channel": channel, "reason": budget_reason},
            )
            return

        normalizer = _NORMALIZERS.get(channel)
        if normalizer is None:
            logger.warning(
                "omnicall_v9.shadow.unknown_channel",
                extra={"channel": channel, "store_id": store_id},
            )
            return

        try:
            unified = normalizer(payload)
        except Exception as exc:
            logger.error(
                "omnicall_v9.shadow.normalize_failed",
                extra={
                    "channel": channel,
                    "store_id": store_id,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                },
            )
            if observer:
                observer.record_normalize_error(channel, exc.__class__.__name__)
            return

        result = safe_process_unified(unified, run_minimal_pipeline, log=logger)

        route = getattr(result.processor_result, "route", None)
        if observer:
            observer.record_shadow_processed(
                channel=channel,
                accepted=result.accepted,
                route=str(route) if route else None,
                reason=result.reason,
                error_type=result.error_type,
            )

        log_pipeline_event(
            "omnicall_v9.shadow.processed",
            unified,
            channel=channel,
            store_id=store_id,
            v9_accepted=result.accepted,
            v9_reason=result.reason,
            v9_route=str(route) if route else None,
            v9_handler=getattr(result.processor_result, "handler_name", None),
            shadow_mode=True,
            shadow_budget_reason=budget_reason,
            duration_ms=result.duration_ms,
        )

    except Exception as exc:
        logger.error(
            "omnicall_v9.shadow.unhandled_error",
            extra={
                "channel": channel,
                "store_id": store_id,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            },
        )
