"""services/store_resolver.py — Résolution du store_id depuis un identifiant social.

Implémentation production avec cache à 3 niveaux :
  1. Cache local in-process (dict + TTL) — <5 ms, zéro I/O.
  2. Cache Redis (TTL 5 min) — partagé entre workers, ~1 ms.
  3. DB PostgreSQL via StoreSocialMapping — vérité absolue.

Exposition publique :
  - resolve_store_id_from_social_id(account_id, channel) -> int | None
  - resolve_store_id_from_phone(phone_number_id) -> int | None
  - invalidate_store_cache(channel, account_id) — après un changement de mapping
  - _cache_key, _local_cache — exposés pour les smoke tests

Canaux supportés : whatsapp | instagram | facebook | tiktok | messenger
"""
from __future__ import annotations

import logging
import time
from typing import Any

# AUDIT FIX : import remonté au niveau module (était importé localement dans
# _db_resolve_social/_db_resolve_phone). tests/test_store_resolver.py mocke
# `services.store_resolver.AsyncSessionLocal`, ce qui échouait avec
# AttributeError tant que le nom n'existait qu'en local scope. Comportement
# runtime inchangé.
from models.database import AsyncSessionLocal  # noqa: F401

logger = logging.getLogger("store_resolver")

# ── Cache in-process ──────────────────────────────────────────────────────────
# Structure : {cache_key: (expire_monotonic, store_id | None)}
_local_cache: dict[str, tuple[float, int | None]] = {}
_LOCAL_TTL = 300.0  # 5 minutes


def _cache_key(channel: str, account_id: str) -> str:
    """Construit la clé de cache normalisée pour un compte social."""
    return f"store_resolver:{channel}:{account_id}"


def _phone_cache_key(phone_number_id: str) -> str:
    return f"store_resolver:wa_phone:{phone_number_id}"


def _local_get(key: str) -> tuple[bool, int | None]:
    """Lit depuis le cache local. Retourne (hit, store_id)."""
    entry = _local_cache.get(key)
    if entry is None:
        return False, None
    expire_at, store_id = entry
    if time.monotonic() > expire_at:
        del _local_cache[key]
        return False, None
    return True, store_id


def _local_set(key: str, store_id: int | None, ttl: float = _LOCAL_TTL) -> None:
    """Écrit dans le cache local avec TTL."""
    # Purge des entrées expirées si le cache dépasse 1000 entrées
    if len(_local_cache) > 1000:
        now = time.monotonic()
        expired = [k for k, (exp, _) in _local_cache.items() if exp < now]
        for k in expired:
            _local_cache.pop(k, None)
    _local_cache[key] = (time.monotonic() + ttl, store_id)


# ── Cache Redis ───────────────────────────────────────────────────────────────
_REDIS_TTL = 300  # 5 minutes
_REDIS_PREFIX = "store_resolver:"


async def _get_redis():
    try:
        from lib.redis_client import get_redis as _shared_get_redis
        client = await _shared_get_redis()
        await client.ping()
        return client
    except Exception:
        return None


async def _redis_get(key: str) -> tuple[bool, int | None]:
    """Lit depuis Redis. Retourne (hit, store_id)."""
    redis = await _get_redis()
    if redis is None:
        return False, None
    try:
        val = await redis.get(_REDIS_PREFIX + key)
        if val is None:
            return False, None
        return True, (int(val) if val != "null" else None)
    except Exception:
        return False, None


async def _redis_set(key: str, store_id: int | None) -> None:
    """Écrit dans Redis."""
    redis = await _get_redis()
    if redis is None:
        return
    try:
        val = str(store_id) if store_id is not None else "null"
        await redis.setex(_REDIS_PREFIX + key, _REDIS_TTL, val)
    except Exception:
        pass


# ── Résolution DB ─────────────────────────────────────────────────────────────

async def _db_resolve_social(channel: str, account_id: str) -> int | None:
    """Requête DB sur StoreSocialMapping."""
    try:
        from sqlalchemy import select

        from models.database import StoreSocialMapping
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(StoreSocialMapping).where(
                    StoreSocialMapping.account_id == account_id,
                    StoreSocialMapping.channel == channel,
                    StoreSocialMapping.is_active,
                )
            )
            mapping = result.scalar_one_or_none()
            if mapping:
                return mapping.store_id
    except Exception as exc:
        logger.warning(
            "store_resolver.db_error channel=%s account_id=%s error=%s",
            channel, account_id, exc,
        )
    return None


async def _db_resolve_phone(phone_number_id: str) -> int | None:
    """Requête DB sur StorePhoneMapping (WhatsApp phone_number_id -> store_id)."""
    try:
        from sqlalchemy import select

        from models.database import StorePhoneMapping
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(StorePhoneMapping).where(
                    StorePhoneMapping.phone_number_id == phone_number_id,
                    StorePhoneMapping.is_active,
                )
            )
            mapping = result.scalar_one_or_none()
            if mapping:
                return mapping.store_id
    except Exception as exc:
        logger.warning(
            "store_resolver.db_phone_error phone_number_id=%s error=%s",
            phone_number_id, exc,
        )
    return None


# ── Interface publique ────────────────────────────────────────────────────────

async def resolve_store_id_from_social_id(
    social_account_id: str | None,
    channel: str,
) -> int | None:
    """Résout le store_id depuis un identifiant de compte social.

    Parcourt les 3 niveaux de cache dans l'ordre : local -> Redis -> DB.

    Args:
        social_account_id : ID du compte social (ex: page_id Instagram, WABA ID).
        channel           : Canal (whatsapp|instagram|facebook|tiktok|messenger).

    Returns:
        store_id (int) si trouvé, None sinon.
    """
    if not social_account_id:
        logger.debug("store_resolver.no_account_id channel=%s", channel)
        return None

    key = _cache_key(channel, social_account_id)

    # 1. Cache local
    hit, store_id = _local_get(key)
    if hit:
        try:
            from services.metrics import store_resolver_lookups_total
            store_resolver_lookups_total.labels(channel=channel, source="local", outcome="hit").inc()
        except Exception:
            pass
        logger.debug(
            "store_resolver.cache_hit level=local channel=%s account_id=%s store_id=%s",
            channel, social_account_id, store_id,
        )
        return store_id

    # 2. Cache Redis
    hit, store_id = await _redis_get(key)
    if hit:
        _local_set(key, store_id)
        try:
            from services.metrics import store_resolver_lookups_total
            store_resolver_lookups_total.labels(channel=channel, source="redis", outcome="hit").inc()
        except Exception:
            pass
        logger.debug(
            "store_resolver.cache_hit level=redis channel=%s account_id=%s store_id=%s",
            channel, social_account_id, store_id,
        )
        return store_id

    # 3. DB
    store_id = await _db_resolve_social(channel, social_account_id)

    # Populate caches (même si None — pour éviter DB storms)
    _local_set(key, store_id)
    await _redis_set(key, store_id)

    try:
        from services.metrics import store_resolver_lookups_total
        store_resolver_lookups_total.labels(channel=channel, source="db", outcome="hit" if store_id else "miss").inc()
    except Exception:
        pass

    if store_id:
        logger.info(
            "store_resolver.db_hit channel=%s account_id=%s store_id=%d",
            channel, social_account_id, store_id,
        )
    else:
        logger.info(
            "store_resolver.not_found channel=%s account_id=%s",
            channel, social_account_id,
        )

    return store_id


async def resolve_store_id_from_phone(phone_number_id: str) -> int | None:
    """Résout le store_id depuis un WhatsApp phone_number_id.

    Utilisé par le webhook WhatsApp pour le routing multi-tenant.

    Args:
        phone_number_id : WhatsApp phone_number_id (ex: "107990455914067").

    Returns:
        store_id (int) si trouvé, None sinon.
    """
    if not phone_number_id:
        return None

    key = _phone_cache_key(phone_number_id)

    # Cache local
    hit, store_id = _local_get(key)
    if hit:
        return store_id

    # Cache Redis
    hit, store_id = await _redis_get(key)
    if hit:
        _local_set(key, store_id)
        return store_id

    # DB
    store_id = await _db_resolve_phone(phone_number_id)
    _local_set(key, store_id)
    await _redis_set(key, store_id)

    if store_id:
        logger.info("store_resolver.phone_hit phone_number_id=%s store_id=%d", phone_number_id, store_id)
    else:
        logger.warning("store_resolver.phone_not_found phone_number_id=%s", phone_number_id)

    return store_id


async def invalidate_store_cache(channel: str, account_id: str) -> None:
    """Invalide les entrées de cache pour un compte social.

    À appeler après toute modification de StoreSocialMapping.
    """
    key = _cache_key(channel, account_id)
    _local_cache.pop(key, None)
    redis = await _get_redis()
    if redis:
        try:
            await redis.delete(_REDIS_PREFIX + key)
        except Exception:
            pass
    logger.info("store_resolver.cache_invalidated channel=%s account_id=%s", channel, account_id)
