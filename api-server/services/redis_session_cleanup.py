"""services/redis_session_cleanup.py — Nettoyage des sessions orphelines Redis.

Nettoie périodiquement les clés Redis liées à l'authentification qui peuvent
survivre à des crashes, rollbacks partiels ou à une invalidation incomplète :
  - reset_token:*
  - auth:pw_changed:*
  - refresh:blacklist:*

Stratégie :
  - reset_token:*  -> supprime les tokens absents, expirés, utilisés ou liés à un utilisateur supprimé
  - auth:pw_changed:* -> supprime les marqueurs d'utilisateurs inexistants et restaure un TTL si absent
  - refresh:blacklist:* -> supprime les clés sans TTL (sinon elles s'accumulent indéfiniment)

Fail-open : si Redis est indisponible, le job remonte une erreur au worker Celery
qui appliquera sa stratégie de retry.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import AsyncIterator

from sqlalchemy import select

from models.database import AsyncSessionLocal, PasswordResetToken, User
from services.redis_lock import get_redis

logger = logging.getLogger(__name__)

SCAN_COUNT = int(os.getenv("ORPHAN_SESSION_SCAN_COUNT", "200"))
PASSWORD_CHANGE_TTL_SECONDS = int(os.getenv("AUTH_PASSWORD_CHANGE_TTL_SECONDS", str(24 * 3600 + 300)))


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


async def _scan_keys(redis_client, pattern: str, count: int) -> AsyncIterator[str]:
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=count)
        for key in keys:
            yield _decode(key)
        if cursor == 0:
            break


async def cleanup_orphaned_redis_sessions(batch_size: int | None = None) -> dict[str, int]:
    stats: dict[str, int] = {
        "reset_tokens_scanned": 0,
        "password_change_keys_scanned": 0,
        "refresh_blacklist_scanned": 0,
        "deleted": 0,
        "reset_tokens_deleted": 0,
        "password_change_deleted": 0,
        "refresh_blacklist_deleted": 0,
        "ttls_restored": 0,
        "errors": 0,
    }

    redis_client = get_redis()
    scan_count = batch_size or SCAN_COUNT
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        async for key in _scan_keys(redis_client, "reset_token:*", scan_count):
            stats["reset_tokens_scanned"] += 1
            token = key.split(":", 1)[1] if ":" in key else ""
            try:
                ttl = await redis_client.ttl(key)
                if ttl == -2:
                    continue

                result = await db.execute(
                    select(PasswordResetToken).where(PasswordResetToken.token == token)
                )
                token_row = result.scalar_one_or_none()

                should_delete = False
                if token_row is None:
                    should_delete = True
                elif token_row.used or token_row.expires_at <= now:
                    should_delete = True
                else:
                    user = await db.get(User, token_row.user_id)
                    if user is None or not user.is_active:
                        should_delete = True

                if should_delete:
                    await redis_client.delete(key)
                    stats["deleted"] += 1
                    stats["reset_tokens_deleted"] += 1
                    continue

                if ttl < 0 and token_row is not None:
                    remaining = max(int((token_row.expires_at - now).total_seconds()), 1)
                    await redis_client.expire(key, remaining)
                    stats["ttls_restored"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("redis_session_cleanup reset_token failed key=%s error=%s", key, exc)

        async for key in _scan_keys(redis_client, "auth:pw_changed:*", scan_count):
            stats["password_change_keys_scanned"] += 1
            try:
                ttl = await redis_client.ttl(key)
                if ttl == -2:
                    continue

                user_id_raw = key.rsplit(":", 1)[-1]
                if not user_id_raw.isdigit():
                    await redis_client.delete(key)
                    stats["deleted"] += 1
                    stats["password_change_deleted"] += 1
                    continue

                user = await db.get(User, int(user_id_raw))
                if user is None:
                    await redis_client.delete(key)
                    stats["deleted"] += 1
                    stats["password_change_deleted"] += 1
                    continue

                if ttl < 0:
                    await redis_client.expire(key, PASSWORD_CHANGE_TTL_SECONDS)
                    stats["ttls_restored"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("redis_session_cleanup auth:pw_changed failed key=%s error=%s", key, exc)

        async for key in _scan_keys(redis_client, "refresh:blacklist:*", scan_count):
            stats["refresh_blacklist_scanned"] += 1
            try:
                ttl = await redis_client.ttl(key)
                if ttl == -2:
                    continue
                if ttl < 0:
                    await redis_client.delete(key)
                    stats["deleted"] += 1
                    stats["refresh_blacklist_deleted"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.warning("redis_session_cleanup refresh:blacklist failed key=%s error=%s", key, exc)

    logger.info("redis_session_cleanup completed stats=%s", stats)
    return stats
