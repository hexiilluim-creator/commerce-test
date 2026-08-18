"""
services/agent_mute.py — Système de prise de main / sourdine IA

3 modes, stockés en Redis (pas de colonne DB — TTL natif gère la sourdine) :

1. BOT ACTIF (défaut) : l'IA répond à tous les messages entrants de ce store.

2. SOURDINE GLOBALE (store-level mute) :
   - L'IA se tait complètement pour toute la boutique pendant N minutes.
   - Cas d'usage : maintenance, démo en direct, réponse manuelle générale.
   - Clé Redis : mute:store:{store_id}  -> "1"  TTL = mute_minutes * 60
   - API : POST /api/v1/whatsapp/agent/mute  {"minutes": 30}
   - API : DELETE /api/v1/whatsapp/agent/mute  (reprendre immédiatement)

3. PRISE DE MAIN PER-CLIENT (customer takeover) :
   - L'IA répond normalement à tous les clients SAUF ce client précis.
   - Cas d'usage : client difficile, négociation, SAV sensible.
   - Le marchand prend la main, répond manuellement via l'interface.
   - Clé Redis : takeover:{store_id}:{customer_phone} -> "1"  TTL = takeover_minutes * 60
   - API : POST /api/v1/whatsapp/agent/takeover/{phone}  {"minutes": 120}
   - API : DELETE /api/v1/whatsapp/agent/takeover/{phone}  (rendre la main à l'IA)
   - API : GET  /api/v1/whatsapp/agent/status  (voir l'état global)

Intégration webhook (whatsapp.py) :
   Avant de router un message vers l'agent, appeler should_ai_respond().
   Si False -> logguer et laisser le marchand répondre manuellement.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timezone

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_MUTE_MINUTES = 30
DEFAULT_TAKEOVER_MINUTES = 120
MAX_MUTE_MINUTES = 1440          # 24h max
MAX_TAKEOVER_MINUTES = 1440      # 24h max


# ── Redis key helpers ─────────────────────────────────────────────────────────
def _k_mute(store_id: int) -> str:
    return f"agent_mute:store:{store_id}"


def _k_takeover(store_id: int, customer_phone: str) -> str:
    # Normalize phone: strip + and spaces for consistent key
    phone = customer_phone.lstrip("+").replace(" ", "")
    return f"agent_takeover:{store_id}:{phone}"


def _k_takeover_pattern(store_id: int) -> str:
    return f"agent_takeover:{store_id}:*"


def get_redis_client():
    """Returns a Redis client instance. Can be patched in tests."""
    from config import settings
    if settings.ENV == "test":
        # P0-FIX: Fail-safe mock for integration tests where Redis is not available
        class FakeRedis:
            async def get(self, *a, **k): return None
            async def setex(self, *a, **k): return True
            async def delete(self, *a, **k): return True
            async def exists(self, *a, **k): return False
            async def ttl(self, *a, **k): return -1
            async def scan(self, c, *a, **k): return 0, []
        return FakeRedis()

    try:
        from services.redis_lock import get_redis as _get_redis
        return _get_redis()
    except ImportError:
        try:
            from lib.redis_client import get_redis as _get_redis_lib
            return _get_redis_lib()
        except ImportError:
            import redis.asyncio as aioredis
            return aioredis.from_url(settings.REDIS_URL or "redis://localhost:6379")

async def get_redis():
    """Internal wrapper that handles both sync and async getters."""
    client = get_redis_client()
    if hasattr(client, "__await__"):
        return await client
    return client

# ── Core check ────────────────────────────────────────────────────────────────
async def should_ai_respond(
    store_id: int,
    customer_phone: str,
) -> tuple[bool, str]:
    """
    Retourne (should_respond: bool, reason: str).

    Appelé dans receive_webhook() avant de router vers l'agent IA.
    Fast path Redis — ne touche pas la DB.

    Returns:
        (True, "active")     -> IA répond normalement
        (False, "muted")     -> sourdine globale active pour ce store
        (False, "takeover")  -> prise de main manuelle sur ce client
    """
    try:
        r = await get_redis()

        # 1. Store-wide mute (plus prioritaire)
        muted = await r.exists(_k_mute(store_id))
        if muted:
            return False, "muted"

        # 2. Per-customer takeover
        taken_over = await r.exists(_k_takeover(store_id, customer_phone))
        if taken_over:
            return False, "takeover"

        return True, "active"

    except Exception as e:
        # Redis unavailable -> fail-open (laissez l'IA répondre plutôt que de tout bloquer)
        logger.warning("agent_mute: Redis unavailable — failing open: %s", e)
        return True, "active"


# ── Store-wide mute ───────────────────────────────────────────────────────────
async def mute_store(store_id: int, minutes: int = DEFAULT_MUTE_MINUTES) -> dict:
    """
    Met l'IA en sourdine pour toute la boutique pendant `minutes` minutes.
    Le TTL Redis gère l'expiration automatiquement.
    """
    minutes = max(1, min(minutes, MAX_MUTE_MINUTES))
    ttl_seconds = minutes * 60

    r = await get_redis()
    await r.setex(_k_mute(store_id), ttl_seconds, "1")

    expires_at = datetime.now(UTC).timestamp() + ttl_seconds
    logger.info("agent_mute: store %s muted for %d min", store_id, minutes)

    return {
        "status": "muted",
        "store_id": store_id,
        "minutes": minutes,
        "expires_at_unix": expires_at,
    }


async def unmute_store(store_id: int) -> dict:
    """Reprend l'IA immédiatement (supprime la sourdine)."""
    r = await get_redis()
    await r.delete(_k_mute(store_id))

    logger.info("agent_mute: store %s unmuted", store_id)
    return {"status": "active", "store_id": store_id}


async def get_mute_status(store_id: int) -> dict:
    """Retourne l'état de la sourdine globale et le TTL restant."""
    r = await get_redis()

    ttl = await r.ttl(_k_mute(store_id))
    if ttl <= 0:
        return {"muted": False, "remaining_seconds": 0}

    return {"muted": True, "remaining_seconds": ttl, "remaining_minutes": ttl // 60}


# ── Per-customer takeover ─────────────────────────────────────────────────────
async def takeover_customer(
    store_id: int,
    customer_phone: str,
    minutes: int = DEFAULT_TAKEOVER_MINUTES,
) -> dict:
    """
    Prend la main sur un client : l'IA ne répondra plus à ce client
    pendant `minutes` minutes (le marchand répond manuellement).
    Tous les autres clients restent gérés par l'IA.
    """
    minutes = max(1, min(minutes, MAX_TAKEOVER_MINUTES))
    ttl_seconds = minutes * 60

    r = await get_redis()
    key = _k_takeover(store_id, customer_phone)
    await r.setex(key, ttl_seconds, "1")

    expires_at = datetime.now(UTC).timestamp() + ttl_seconds
    logger.info(
        "agent_mute: takeover activated store=%s phone=%s for %d min",
        store_id, customer_phone[:6] + "***", minutes,
    )

    return {
        "status": "takeover",
        "store_id": store_id,
        "customer_phone": customer_phone,
        "minutes": minutes,
        "expires_at_unix": expires_at,
        "message": (
            f"L'IA ne répondra plus à {customer_phone} pendant {minutes} min. "
            f"Vous pouvez répondre manuellement."
        ),
    }


async def release_customer(store_id: int, customer_phone: str) -> dict:
    """Rend la main à l'IA pour ce client immédiatement."""
    r = await get_redis()
    key = _k_takeover(store_id, customer_phone)
    await r.delete(key)

    logger.info(
        "agent_mute: takeover released store=%s phone=%s",
        store_id, customer_phone[:6] + "***",
    )
    return {
        "status": "active",
        "store_id": store_id,
        "customer_phone": customer_phone,
        "message": "L'IA reprend la main sur ce client.",
    }


async def get_takeover_status(store_id: int, customer_phone: str) -> dict:
    """Retourne l'état de la prise de main pour un client."""
    r = await get_redis()

    ttl = await r.ttl(_k_takeover(store_id, customer_phone))
    if ttl <= 0:
        return {
            "taken_over": False,
            "customer_phone": customer_phone,
            "remaining_seconds": 0,
        }

    return {
        "taken_over": True,
        "customer_phone": customer_phone,
        "remaining_seconds": ttl,
        "remaining_minutes": ttl // 60,
    }


# ── Global status (all active controls for a store) ───────────────────────────
async def get_store_agent_status(store_id: int) -> dict:
    """
    Vue complète de l'état du contrôle IA pour une boutique :
    - Sourdine globale (TTL restant)
    - Liste des clients en prise de main manuelle (TTL restant)
    """
    r = await get_redis()

    # Mute global
    mute_ttl = await r.ttl(_k_mute(store_id))
    mute_active = mute_ttl > 0

    # Takeovers actifs — scan des clés par pattern
    takeovers = []
    try:
        pattern = _k_takeover_pattern(store_id)
        # Redis SCAN pour éviter un KEYS bloquant en prod
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=100)
            for key in keys:
                ttl = await r.ttl(key)
                if ttl > 0:
                    # Extraire le numéro de téléphone depuis la clé
                    phone = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    takeovers.append({
                        "customer_phone": phone,
                        "remaining_seconds": ttl,
                        "remaining_minutes": ttl // 60,
                    })
            if cursor == 0:
                break
    except Exception as e:
        logger.warning("agent_mute: scan takeovers failed: %s", e)

    return {
        "store_id": store_id,
        "ai_mode": "muted" if mute_active else ("partial" if takeovers else "active"),
        "mute": {
            "active": mute_active,
            "remaining_seconds": max(0, mute_ttl),
            "remaining_minutes": max(0, mute_ttl // 60),
        },
        "takeovers": takeovers,
        "summary": (
            f"IA en sourdine ({mute_ttl // 60} min restantes)"
            if mute_active
            else (
                f"IA active — {len(takeovers)} client(s) en prise de main manuelle"
                if takeovers
                else "IA active — réponse automatique sur tous les clients"
            )
        ),
    }
