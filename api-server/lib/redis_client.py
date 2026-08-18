"""lib/redis_client.py — Point d'entrée unique pour les connexions Redis.

BUG#6 FIX: _get_redis() était réimplémentée indépendamment dans 9 fichiers
(security_overlay/billing_overlay.py, services/webhook_reliability.py,
services/conversation_memory_service.py, services/message_queue.py,
services/store_resolver.py, services/emotion_alerts.py, services/ai_guardrails.py,
services/emotion_detection.py, services/llm_gateway.py) — risque de
configuration divergente (timeouts, pool, TLS) entre les fichiers.

Tous ces fichiers doivent maintenant importer get_redis depuis ce module.
"""
from __future__ import annotations

import redis.asyncio as aioredis

from config import settings

_pool: aioredis.ConnectionPool | None = None


async def get_redis() -> aioredis.Redis:
    """Retourne une connexion Redis depuis le pool partagé (singleton)."""
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=getattr(settings, "REDIS_MAX_CONNECTIONS", 10),
            socket_timeout=getattr(settings, "REDIS_SOCKET_TIMEOUT", 5.0),
            socket_connect_timeout=getattr(settings, "REDIS_SOCKET_CONNECT_TIMEOUT", 5.0),
            decode_responses=True,
        )
    return aioredis.Redis(connection_pool=_pool)


async def close_redis_pool() -> None:
    """Ferme le pool Redis proprement — à appeler dans le shutdown lifespan."""
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None
