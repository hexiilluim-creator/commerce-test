"""services/redis_lock.py — Client Redis partagé et lock distribué.

BLOC 8 FIX: Pool de connexions Redis configuré via settings.
  - max_connections=settings.REDIS_MAX_CONNECTIONS (défaut 10 par worker)
  - socket_timeout / socket_connect_timeout depuis settings
  - Une seule instance partagée (singleton par worker Uvicorn)

Architecture de pool :
  3 pods × 8 workers × 10 connexions max = 240 connexions Redis totales.
  Redis 7 supporte 10 000 connexions par défaut — largement suffisant.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis():
    """Retourne le client Redis async partagé (singleton par worker, pool configuré)."""
    global _redis_client
    
    # P0-FIX (audit): check if we should return a mock for tests
    # In some test environments, redis-mock might be used or we might want to bypass
    if _redis_client is not None:
        return _redis_client

    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            from config import settings  # local import to avoid circular deps at module load

            _redis_client = aioredis.Redis.from_url(
                settings.REDIS_URL,
                decode_responses=False,
                max_connections=int(getattr(settings, "REDIS_MAX_CONNECTIONS", 10)),
                socket_timeout=float(getattr(settings, "REDIS_SOCKET_TIMEOUT", 5.0)),
                socket_connect_timeout=float(
                    getattr(settings, "REDIS_SOCKET_CONNECT_TIMEOUT", 3.0)
                ),
            )
            logger.debug(
                "redis_lock: pool created max_connections=%s",
                getattr(settings, "REDIS_MAX_CONNECTIONS", 10),
            )
        except ImportError:
            raise RuntimeError("redis package not installed. Run: pip install redis")
    return _redis_client


def get_redis_sync():
    """Retourne un client Redis synchrone (usage Celery/scripts uniquement)."""
    try:
        import redis as redis_lib

        from config import settings  # noqa: PLC0415

        return redis_lib.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=float(getattr(settings, "REDIS_SOCKET_CONNECT_TIMEOUT", 3.0)),
            socket_timeout=float(getattr(settings, "REDIS_SOCKET_TIMEOUT", 5.0)),
        )
    except ImportError:
        return None


class _NoOpLockService:
    """Lock distribué no-op (fallback si Redis indisponible — dev/CI sans Redis)."""

    @asynccontextmanager
    async def acquire(self, key: str, timeout: int = 30):
        yield True

    async def try_acquire(self, key: str, timeout: int = 30) -> bool:
        return True

    async def release(self, key: str) -> None:
        pass


class _RedisLockService:
    """Lock distribué basé sur Redis SET NX — atomique et cross-worker."""

    def __init__(self) -> None:
        self._prefix = "omnicall:lock:"

    @asynccontextmanager
    async def acquire(self, key: str, timeout: int = 30):
        r = get_redis()
        lock_key = f"{self._prefix}{key}"
        acquired = await r.set(lock_key, "1", nx=True, ex=timeout)
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await r.delete(lock_key)

    async def try_acquire(self, key: str, timeout: int = 30) -> bool:
        r = get_redis()
        lock_key = f"{self._prefix}{key}"
        result = await r.set(lock_key, "1", nx=True, ex=timeout)
        return bool(result)

    async def release(self, key: str) -> None:
        r = get_redis()
        await r.delete(f"{self._prefix}{key}")


try:
    lock_service = _RedisLockService()
except Exception as _exc:
    logger.warning("redis_lock: failed to init _RedisLockService: %s", _exc)
    lock_service = _NoOpLockService()


async def acquire_lock(key: str, ttl: int = 30) -> str | None:
    """Acquire a distributed slot lock and return a release token when held."""
    acquired = await lock_service.try_acquire(key, timeout=ttl)
    return "1" if acquired else None


async def release_lock(key: str, token: str | None = None) -> None:
    """Release a slot lock acquired through :func:`acquire_lock`."""
    if token is not None:
        await lock_service.release(key)
