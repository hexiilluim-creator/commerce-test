"""api/v1/health.py — Detailed health checks (P2-B)"""

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])

# V28 P0-fix : "version": "25.0.0" était codé en dur ici, indépendamment du
# VERSION réel du package (28.0.0 au moment de ce correctif). Un /health
# interrogé en monitoring/exploitation affichait donc une version périmée.
# Lecture depuis api-server/VERSION (copie de la racine, incluse dans le
# contexte de build Docker de api-server/ — la racine du repo n'y est pas
# copiée). Garder les deux fichiers synchronisés à chaque release.
_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def _read_app_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        logger.warning("health: VERSION file introuvable (%s) — version inconnue", _VERSION_FILE)
        return "unknown"


APP_VERSION = _read_app_version()


@router.get("")
@router.get("/")
async def health_simple():
    """Fast liveness probe — just confirms the process is alive.

    P0 : expose les deux variantes (`/health` et `/health/`) pour rester
    compatible avec `redirect_slashes=False` activé dans `main.py`.
    Public — ne révèle aucune information système.
    """
    return {"status": "ok", "version": APP_VERSION}


# ── Sub-check helpers (REF-2: extracted from 143-line monolith) ───────────────

async def _check_database() -> dict:
    try:
        from models.database import AsyncSessionLocal
        t0 = time.monotonic()
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "error", "detail": "Internal check failed"}


async def _check_redis() -> dict:
    try:
        import redis.asyncio as aioredis

        from config import settings
        t0 = time.monotonic()
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.ping()
        await r.aclose()
        return {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "error", "detail": "Internal check failed"}


async def _check_celery_queues() -> tuple[dict, bool]:
    """Returns (result_dict, is_degraded)."""
    try:
        import redis.asyncio as aioredis

        from config import settings
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        queues = [
            "billing", "whatsapp", "social", "ai", "celery",
            "whatsapp.dlq", "payments.dlq", "social.dlq", "billing.dlq", "ai.dlq",
        ]
        depths = {}
        degraded = False
        for q in queues:
            depth = await r.llen(q)
            depths[q] = depth
            if depth > 1000:
                degraded = True
            if q.endswith(".dlq") and depth > 0:
                degraded = True
        await r.aclose()
        return {"status": "ok", "depths": depths}, degraded
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "unknown", "detail": "Internal check failed"}, False


async def _check_openai() -> dict:
    try:
        from config import settings
        status = "configured" if settings.OPENAI_API_KEY.startswith("sk-") else "misconfigured"
        return {"status": status}
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "error", "detail": "Internal check failed"}


async def _check_disk() -> tuple[dict, bool]:
    try:
        import shutil
        usage = shutil.disk_usage("/")
        pct = round(usage.used / usage.total * 100, 1) if usage.total else 0
        status = "ok" if pct < 85 else ("warning" if pct < 95 else "critical")
        return {"status": status, "used_pct": pct, "free_gb": round(usage.free / 1e9, 2)}, pct >= 95
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "unknown", "detail": "Internal check failed"}, False


async def _check_celery_workers() -> tuple[dict, bool]:
    try:
        from services.celery_app import celery_app
        i = celery_app.control.inspect(timeout=1.0)
        active_workers = i.ping() or {}
        ok = bool(active_workers)
        return {
            "status": "ok" if ok else "degraded",
            "count": len(active_workers),
            "workers": list(active_workers.keys()),
        }, not ok
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "unknown", "detail": "Internal check failed"}, False


async def _check_circuit_breakers() -> tuple[dict, bool]:
    try:
        from services.circuit_breaker import list_breakers

        breakers = list_breakers()
        breaker_states = {
            entry.get("name", f"breaker_{idx}"): entry.get("state", "unknown")
            for idx, entry in enumerate(breakers)
        }
        open_count = sum(1 for state in breaker_states.values() if state == "open")
        degraded = open_count > 0
        return {
            "status": "degraded" if degraded else "ok",
            "count": len(breaker_states),
            "open_count": open_count,
            "breakers": breaker_states,
        }, degraded
    except Exception:
        logger.error("health_check_error", exc_info=True)
        return {"status": "unknown", "detail": "Internal check failed", "breakers": {}}, False


from middleware.auth import require_internal_health_rate_limit, require_internal_health_token


@router.get(
    "/detailed",
    dependencies=[
        Depends(require_internal_health_token),
        Depends(require_internal_health_rate_limit),
    ],
)
async def health_detailed():
    """
    Full readiness probe — checks DB, Redis, Celery, disk, circuit breakers.
    PROTECTED: requires X-Internal-Token header and is rate-limited to 1 request / 10 seconds.
    """

    overall = "ok"
    results = {}

    db_result = await _check_database()
    results["database"] = db_result
    if db_result["status"] != "ok":
        overall = "degraded"

    redis_result = await _check_redis()
    results["redis"] = redis_result
    if redis_result["status"] != "ok":
        overall = "degraded"

    queue_result, queue_degraded = await _check_celery_queues()
    results["celery_queues"] = queue_result
    if queue_degraded and overall == "ok":
        overall = "degraded"

    results["openai"] = await _check_openai()

    disk_result, disk_degraded = await _check_disk()
    results["disk"] = disk_result
    if disk_degraded and overall == "ok":
        overall = "degraded"

    worker_result, worker_degraded = await _check_celery_workers()
    results["celery_workers"] = worker_result
    if worker_degraded and overall == "ok":
        overall = "degraded"

    cb_result, cb_degraded = await _check_circuit_breakers()
    results["circuit_breakers"] = cb_result
    if cb_degraded and overall == "ok":
        overall = "degraded"

    payload = {"status": overall, "components": results, "timestamp": time.time()}
    # AUDIT FIX : cet endpoint /health/detailed est informationnel
    # (dashboards, supervision globale) et reste volontairement HTTP 200 même
    # en statut "degraded" (ex: un circuit breaker Stripe ouvert ne rend pas
    # le service injoignable). La readiness stricte (503 sur panne réelle)
    # est déléguée aux sous-endpoints dédiés /health/db et /health/redis
    # ci-dessous.
    return JSONResponse(status_code=200, content=payload)


@router.get("/live")
async def health_live():
    """Kubernetes/docker liveness probe — process alive only."""
    return {"status": "ok", "probe": "live"}


@router.get("/ready")
async def health_ready():
    """Strict readiness probe — DB and Redis must both be reachable."""
    db_result = await _check_database()
    redis_result = await _check_redis()
    ok = db_result.get("status") == "ok" and redis_result.get("status") == "ok"
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "database": db_result, "redis": redis_result, "probe": "ready"},
    )


@router.get("/db")
async def health_db():
    """Readiness sub-check for the database. Returns 503 if unreachable.

    AUDIT FIX : renvoyait toujours 200 même quand status == "error", ce qui
    masquait les pannes DB aux probes/monitoring qui ne lisent que le code HTTP.
    """
    result = await _check_database()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(status_code=status_code, content=result)


@router.get("/redis")
async def health_redis():
    """Readiness sub-check for Redis. Returns 503 if unreachable.

    AUDIT FIX (confirmé par audit outillé) : cet endpoint renvoyait
    systématiquement HTTP 200 même quand `_check_redis()` retournait
    {"status": "error", ...} après une connexion Redis refusée. Un load
    balancer ou une probe Kubernetes basée sur le code HTTP considérait donc
    le service comme sain alors que Redis était injoignable.
    """
    result = await _check_redis()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(status_code=status_code, content=result)

