"""services/ai_guardrails.py — Guardrails IA et gestion des crédits tenant.

Implémentation production :
  - Redis reste le backend primaire pour les compteurs temps réel.
  - En production/staging, le fallback en cas d'indisponibilité Redis est
    partagé via la base de données (ledger credit_events), pas via mémoire locale.
  - Le fallback mémoire est conservé uniquement pour dev/test/CI afin de garder
    les tests rapides et de ne pas dépendre d'un Redis externe.
  - check_tenant_credit  : vérifie sans déduire.
  - deduct_tenant_credit : déduit de manière atomique (Redis) et persiste un ledger.
  - get_tenant_credit_stats : stats pour /billing/usage.

Coûts :
  text  = 1 crédit
  audio = 5 crédits
  image = 10 crédits
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("ai_guardrails")

# Fallback in-memory DEV/TEST uniquement (single-worker)
_MEMORY_CREDITS: dict[str, int] = {}   # clé: "credits:{store_id}:{YYYYMM}"
_MEMORY_USED: dict[str, int] = {}      # clé: "used:{store_id}:{YYYYMM}"

# ── Quota par défaut (crédits IA par plan, miroir de plan_limits) ─────────────
_DEFAULT_QUOTAS: dict[str, int] = {
    "free": 0,
    "starter": 500,
    "business": 2000,
    "premium": 5000,
    "pro_whatsapp": 10000,
    "pro": 5000,
    "enterprise": 20000,
}


def _month_suffix() -> str:
    return datetime.now(UTC).strftime("%Y%m")


def _month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _credit_key(store_id: int) -> str:
    return f"ai_credits:remaining:{store_id}:{_month_suffix()}"


def _used_key(store_id: int) -> str:
    return f"ai_credits:used:{store_id}:{_month_suffix()}"


def _allocated_key(store_id: int) -> str:
    return f"ai_credits:allocated:{store_id}:{_month_suffix()}"


def _allow_memory_fallback() -> bool:
    env = os.getenv("ENV", "development").strip().lower()
    return env in {"development", "dev", "test"} or bool(os.getenv("PYTEST_CURRENT_TEST"))


# ── Redis helper ──────────────────────────────────────────────────────────────

async def _get_redis():
    """Retourne le client Redis async (pool partagé) ou None si indisponible."""
    try:
        from lib.redis_client import get_redis as _shared_get_redis
        client = await _shared_get_redis()
        await client.ping()
        return client
    except Exception:
        return None


# Alias demandé par auth.py : from services.ai_guardrails import get_redis
def get_redis():
    """Retourne un client Redis.
    
    NOTE: Bien que ce soit une fonction synchrone, elle retourne un client 
    redis.asyncio.Redis pour compatibilité avec les appels 'await r.get()' 
    dans auth.py.
    """
    import redis.asyncio as aioredis
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return aioredis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1)


# ── DB helpers (fallback partagé cross-worker) ────────────────────────────────

async def _get_plan_quota(store_id: int) -> int:
    """Lit le quota mensuel du plan actif depuis la DB ou le catalogue statique."""
    try:
        from models.database import AsyncSessionLocal
        from services.saas_billing import get_active_subscription, get_plan_by_code
        async with AsyncSessionLocal() as db:
            sub = await get_active_subscription(db, store_id)
            plan_code = sub.plan_code if sub else "free"
            plan = await get_plan_by_code(db, plan_code)
            if plan is not None:
                return int((plan or {}).get("monthly_ai_credits", 0))
            return int(_DEFAULT_QUOTAS.get(plan_code, 0))
    except Exception as exc:
        logger.warning("_get_plan_quota db error store_id=%d: %s", store_id, exc)
        return 0


async def _get_db_credit_state(store_id: int) -> tuple[int | None, int]:
    """Retourne (remaining, used) depuis le ledger du mois courant.

    remaining = dernier balance_after connu pour le mois courant.
    used      = somme des consommations du mois courant.
    """
    try:
        from sqlalchemy import text

        from models.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            latest = await db.execute(
                text(
                    """
                    SELECT balance_after
                    FROM credit_events
                    WHERE store_id = :sid
                      AND created_at >= :month_start
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"sid": store_id, "month_start": _month_start()},
            )
            balance = latest.scalar_one_or_none()

            used_result = await db.execute(
                text(
                    """
                    SELECT COALESCE(SUM(ABS(credits_delta)), 0)
                    FROM credit_events
                    WHERE store_id = :sid
                      AND created_at >= :month_start
                      AND event_type IN ('usage', 'deduct')
                    """
                ),
                {"sid": store_id, "month_start": _month_start()},
            )
            used = int(used_result.scalar() or 0)
            return (int(balance) if balance is not None else None, used)
    except Exception as exc:
        logger.warning("_get_db_credit_state store_id=%d failed: %s", store_id, exc)
        return (None, 0)


async def _persist_credit_event(
    store_id: int,
    event_type: str,
    credits_delta: int,
    balance_after: int,
    description: str,
) -> None:
    """Persiste un événement de crédits dans le ledger partagé."""
    try:
        from sqlalchemy import text

        from models.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO credit_events
                        (store_id, event_type, credits_delta, balance_after, description, created_at)
                    VALUES
                        (:sid, :event_type, :delta, :balance_after, :description, :created_at)
                    """
                ),
                {
                    "sid": store_id,
                    "event_type": event_type,
                    "delta": credits_delta,
                    "balance_after": max(0, balance_after),
                    "description": description,
                    "created_at": datetime.now(UTC),
                },
            )
            await db.commit()
    except Exception as exc:
        logger.warning(
            "_persist_credit_event failed store_id=%d event=%s: %s",
            store_id,
            event_type,
            exc,
        )


async def _shared_remaining_balance(store_id: int, quota: int) -> int:
    """Retourne un solde cohérent cross-worker si Redis est indisponible."""
    if _allow_memory_fallback():
        return _MEMORY_CREDITS.get(_credit_key(store_id), quota)

    remaining, _used = await _get_db_credit_state(store_id)
    if remaining is not None:
        return remaining
    return quota


async def _ensure_credits_initialized(store_id: int, redis) -> int:
    """S'assure que le quota mensuel est initialisé dans Redis.

    Si la clé n'existe pas (nouveau mois ou première fois), lit le quota
    depuis la DB et l'initialise avec un TTL jusqu'à la fin du mois.

    Returns:
        Quota alloué pour ce mois.
    """
    allocated_key = _allocated_key(store_id)
    credit_key = _credit_key(store_id)

    if redis:
        try:
            allocated_str = await redis.get(allocated_key)
            if allocated_str is not None:
                return int(allocated_str)
        except Exception:
            pass

        try:
            credit_str = await redis.get(credit_key)
            if credit_str is not None:
                return int(credit_str)
        except Exception:
            pass

    now = datetime.now(UTC)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    ttl_seconds = int((next_month - now).total_seconds()) + 86400

    quota = await _get_plan_quota(store_id)

    if redis:
        try:
            pipe = redis.pipeline()
            pipe.set(allocated_key, quota, ex=ttl_seconds, nx=True)
            pipe.set(credit_key, quota, ex=ttl_seconds, nx=True)
            await pipe.execute()
        except Exception as exc:
            logger.warning("_ensure_credits_initialized redis error store_id=%d: %s", store_id, exc)

    if _allow_memory_fallback() and credit_key not in _MEMORY_CREDITS:
        _MEMORY_CREDITS[credit_key] = quota

    return quota


# ── Interface publique ────────────────────────────────────────────────────────

async def check_tenant_credit(store_id: int, cost: int = 1) -> bool:
    """Vérifie si le tenant dispose de suffisamment de crédits IA.

    N'effectue aucune déduction — appeler deduct_tenant_credit après usage.
    """
    redis = await _get_redis()
    quota = await _ensure_credits_initialized(store_id, redis)

    if cost <= 0:
        return True

    if quota == 0:
        logger.debug("check_tenant_credit store_id=%d quota=0 (plan free — IA bloquée)", store_id)
        return False

    if quota < 0:
        return True

    credit_key = _credit_key(store_id)

    if redis:
        try:
            remaining_str = await redis.get(credit_key)
            remaining = int(remaining_str or quota)
            result = remaining >= cost
            logger.debug(
                "check_tenant_credit store_id=%d remaining=%d cost=%d result=%s",
                store_id, remaining, cost, result,
            )
            return result
        except Exception as exc:
            logger.warning(
                "check_tenant_credit redis error store_id=%d: %s — fallback partagé",
                store_id, exc,
            )

    remaining = await _shared_remaining_balance(store_id, quota)
    return remaining >= cost


async def deduct_tenant_credit(store_id: int, cost: int = 1) -> bool:
    """Déduit des crédits IA après consommation réelle.

    Utilise Redis si disponible, sinon un fallback cohérent :
      - dev/test : mémoire locale
      - prod/staging : ledger DB partagé cross-worker
    """
    if cost <= 0:
        return True

    redis = await _get_redis()
    quota = await _ensure_credits_initialized(store_id, redis)
    credit_key = _credit_key(store_id)
    used_key = _used_key(store_id)
    new_balance: int | None = None

    if redis:
        try:
            pipe = redis.pipeline()
            pipe.decrby(credit_key, cost)
            pipe.incrby(used_key, cost)
            results = await pipe.execute()
            new_balance = int(results[0])
            if new_balance < 0:
                await redis.set(credit_key, 0)
                new_balance = 0
            logger.debug(
                "deduct_tenant_credit store_id=%d cost=%d new_balance=%d",
                store_id, cost, max(0, new_balance),
            )
        except Exception as exc:
            logger.warning("deduct_tenant_credit redis error store_id=%d: %s", store_id, exc)

    if new_balance is None:
        current = await _shared_remaining_balance(store_id, quota)
        new_balance = max(0, current - cost)
        if _allow_memory_fallback():
            _MEMORY_CREDITS[credit_key] = new_balance
            _MEMORY_USED[used_key] = _MEMORY_USED.get(used_key, 0) + cost

    await _persist_credit_event(
        store_id=store_id,
        event_type="usage",
        credits_delta=-cost,
        balance_after=new_balance,
        description=f"AI usage cost={cost}",
    )
    return True


async def get_tenant_credit_stats(store_id: int) -> dict[str, Any]:
    """Retourne les statistiques de crédits IA pour un tenant."""
    redis = await _get_redis()
    quota = await _ensure_credits_initialized(store_id, redis)
    credit_key = _credit_key(store_id)
    used_key = _used_key(store_id)

    remaining = quota
    used = 0

    if redis:
        try:
            remaining_str = await redis.get(credit_key)
            used_str = await redis.get(used_key)
            remaining = int(remaining_str) if remaining_str is not None else quota
            used = int(used_str) if used_str is not None else 0
        except Exception as exc:
            logger.warning("get_tenant_credit_stats redis error store_id=%d: %s", store_id, exc)
            if _allow_memory_fallback():
                remaining = _MEMORY_CREDITS.get(credit_key, quota)
                used = _MEMORY_USED.get(used_key, 0)
            else:
                db_remaining, db_used = await _get_db_credit_state(store_id)
                remaining = quota if db_remaining is None else db_remaining
                used = db_used
    else:
        if _allow_memory_fallback():
            remaining = _MEMORY_CREDITS.get(credit_key, quota)
            used = _MEMORY_USED.get(used_key, 0)
        else:
            db_remaining, db_used = await _get_db_credit_state(store_id)
            remaining = quota if db_remaining is None else db_remaining
            used = db_used

    return {
        "store_id": store_id,
        "remaining": max(0, remaining),
        "used": used,
        "allocated": quota,
        "credits_allocated": quota,
        "credits_used": used,
        "credits_remaining": max(0, remaining),
        "credits_percent_used": round((used / quota * 100) if quota > 0 else 0, 1),
        "period": _month_suffix(),
    }


async def add_tenant_credits(store_id: int, amount: int, reason: str = "top_up") -> int:
    """Ajoute des crédits IA à un tenant (achat de recharge, bonus admin)."""
    if amount <= 0:
        current, _used = await _get_db_credit_state(store_id)
        return max(0, current or 0)

    redis = await _get_redis()
    credit_key = _credit_key(store_id)
    allocated_key = _allocated_key(store_id)

    event_type_map = {
        "top_up": "top_up",
        "bonus": "bonus",
        "renewal": "renewal",
        "refund": "refund",
        "monthly_alloc": "allocate",
        "allocate": "allocate",
    }
    event_type = event_type_map.get(reason, "bonus")

    quota = await _get_plan_quota(store_id)
    new_balance: int | None = None

    if redis:
        try:
            if event_type not in {"allocate", "renewal"}:
                await _ensure_credits_initialized(store_id, redis)
            pipe = redis.pipeline()
            pipe.incrby(credit_key, amount)
            pipe.incrby(allocated_key, amount)
            results = await pipe.execute()
            new_balance = int(results[0])
        except Exception as exc:
            logger.warning("add_tenant_credits redis error store_id=%d: %s", store_id, exc)

    if new_balance is None:
        db_remaining, _used = await _get_db_credit_state(store_id)
        if db_remaining is None:
            base_balance = 0 if event_type in {"allocate", "renewal"} else quota
        else:
            base_balance = db_remaining
        new_balance = max(0, base_balance + amount)
        if _allow_memory_fallback():
            _MEMORY_CREDITS[credit_key] = new_balance

    await _persist_credit_event(
        store_id=store_id,
        event_type=event_type,
        credits_delta=amount,
        balance_after=new_balance,
        description=f"credit_add reason={reason} amount={amount}",
    )

    logger.info(
        "add_tenant_credits store_id=%d amount=%d reason=%s new_balance=%d",
        store_id, amount, reason, new_balance,
    )
    return max(0, new_balance)


async def reset_monthly_credits(store_id: int) -> int:
    """Réinitialise les crédits mensuels (appelé par Celery au renouvellement)."""
    redis = await _get_redis()
    quota = await _get_plan_quota(store_id)
    credit_key = _credit_key(store_id)
    used_key = _used_key(store_id)
    allocated_key = _allocated_key(store_id)

    now = datetime.now(UTC)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    ttl = int((next_month - now).total_seconds()) + 86400

    if redis:
        try:
            pipe = redis.pipeline()
            pipe.set(credit_key, quota, ex=ttl)
            pipe.set(allocated_key, quota, ex=ttl)
            pipe.set(used_key, 0, ex=ttl)
            await pipe.execute()
        except Exception as exc:
            logger.warning("reset_monthly_credits redis error store_id=%d: %s", store_id, exc)

    if _allow_memory_fallback():
        _MEMORY_CREDITS[credit_key] = quota
        _MEMORY_USED[used_key] = 0

    await _persist_credit_event(
        store_id=store_id,
        event_type="reset",
        credits_delta=quota,
        balance_after=quota,
        description="monthly credit reset",
    )

    logger.info("reset_monthly_credits store_id=%d quota=%d", store_id, quota)
    return quota
