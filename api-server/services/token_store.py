"""services/token_store.py — legacy Redis token cache.

Le flow de reset mot de passe repose désormais sur la table
`password_reset_tokens` en base. Ce module n'est conservé que pour une
compatibilité transitoire avec d'éventuels tokens historiques stockés dans
Redis.

Sécurité :
  - En production/staging, aucun fallback mémoire n'est autorisé.
  - En dev/test/CI uniquement, un fallback mémoire local est conservé pour les
    tests unitaires qui n'ont pas de Redis externe.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_mem_store: dict[str, tuple[Any, float]] = {}


def _allow_memory_fallback() -> bool:
    env = os.getenv("ENV", "development").strip().lower()
    return env in {"development", "dev", "test"} or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _mem_cleanup() -> None:
    now = time.time()
    expired = [k for k, (_, exp) in _mem_store.items() if exp < now]
    for k in expired:
        del _mem_store[k]


async def set_token(token: str, value: Any, ttl_seconds: int = 3600) -> None:
    """Stocke un token dans Redis. Fallback mémoire DEV/TEST uniquement."""
    try:
        import json

        from services.redis_lock import get_redis
        redis = get_redis()
        await redis.setex(f"tok:{token}", ttl_seconds, json.dumps(value))
        return
    except Exception as exc:
        if not _allow_memory_fallback():
            logger.warning("token_store.set_token: Redis unavailable; memory fallback disabled (%s)", exc)
            return
        logger.debug("token_store.set_token: Redis unavailable (%s) — using memory", exc)

    _mem_cleanup()
    _mem_store[token] = (value, time.time() + ttl_seconds)


async def get_token(token: str) -> Any | None:
    """Lit un token depuis Redis. En production, retourne None si Redis est indisponible."""
    try:
        import json

        from services.redis_lock import get_redis
        redis = get_redis()
        raw = await redis.get(f"tok:{token}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        if not _allow_memory_fallback():
            logger.warning("token_store.get_token: Redis unavailable; memory fallback disabled (%s)", exc)
            return None
        logger.debug("token_store.get_token: Redis unavailable (%s) — using memory", exc)

    entry = _mem_store.get(token)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _mem_store[token]
        return None
    return value


async def delete_token(token: str) -> None:
    """Supprime un token. En production, aucun fallback mémoire n'est utilisé."""
    try:
        from services.redis_lock import get_redis
        redis = get_redis()
        await redis.delete(f"tok:{token}")
        return
    except Exception as exc:
        if not _allow_memory_fallback():
            logger.warning("token_store.delete_token: Redis unavailable; memory fallback disabled (%s)", exc)
            return
        logger.debug("token_store.delete_token: Redis unavailable (%s) — using memory", exc)

    _mem_store.pop(token, None)
