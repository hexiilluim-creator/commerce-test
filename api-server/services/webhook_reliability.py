"""services/webhook_reliability.py — Déduplication idempotente des webhooks entrants.

Implémentation production avec Redis async + fallback in-memory :
  - Redis (cross-worker) : SETNX avec TTL configurable — garantie idempotence
    sur plusieurs instances API (Gunicorn multi-workers, pods K8s).
  - Fallback in-memory (single-worker) : dict avec TTL + purge périodique —
    utilisé uniquement si Redis est indisponible.

Interface publique :
  - claim_webhook_message(*, channel, store_id, message_id, sender_id,
      recipient_id, body) -> bool
      True  = première livraison  -> traiter
      False = doublon détecté    -> ignorer silencieusement

  - release_webhook_claim(channel, store_id, message_id) -> None
      Libère manuellement un claim (utile si le traitement a échoué et
      doit être réessayé immédiatement).

TTL par défaut : 48 h (172800 s) — couvre les cas de retry tardif Meta/Twilio.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Mapping

logger = logging.getLogger("webhook_reliability")

_DEDUP_TTL_SECONDS: int = 172_800
_REDIS_DEDUP_PREFIX: str = "omnicall:webhook:claim:"
_MEM_MAX_ENTRIES: int = 50_000

_SEEN_MESSAGES: dict[str, float] = {}


def _build_claim_key(
    channel: str,
    store_id: int | None,
    message_id: str | None,
    sender_id: str | None,
    recipient_id: str | None,
    body: str | None,
) -> str:
    """Construit une clé de déduplication stable et déterministe."""
    if message_id and message_id.strip():
        raw = f"{channel}:{store_id}:{message_id}"
        return f"{_REDIS_DEDUP_PREFIX}{raw}"

    parts = f"{channel}:{store_id}:{sender_id}:{recipient_id}:{body or ''}"
    content_hash = hashlib.sha256(parts.encode("utf-8")).hexdigest()[:20]
    return f"{_REDIS_DEDUP_PREFIX}{channel}:{store_id}:content:{content_hash}"


def _normalize_signature(header_value: str | None) -> str | None:
    if not header_value:
        return None
    value = header_value.strip()
    if not value:
        return None
    return value.removeprefix("sha256=")


def verify_signature(payload: bytes, app_secret: str, header_value: str | None) -> bool:
    """Verify X-Hub-Signature-256 in timing-safe fashion."""
    signature = _normalize_signature(header_value)
    if not signature or not app_secret:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def verify_signature_from_headers(
    headers: Mapping[str, str] | Mapping[str, Any], payload: bytes, app_secret: str
) -> bool:
    header_value = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
    return verify_signature(payload, app_secret, header_value)


async def _get_redis():
    try:
        from lib.redis_client import get_redis as _shared_get_redis

        client = await _shared_get_redis()
        await client.ping()
        return client
    except Exception as exc:
        logger.debug("webhook_reliability redis unavailable: %s", exc)
        return None


def _mem_purge_expired() -> None:
    now = time.monotonic()
    expired = [k for k, exp in _SEEN_MESSAGES.items() if exp < now]
    for k in expired:
        _SEEN_MESSAGES.pop(k, None)


async def claim_webhook_message(
    *,
    channel: str,
    store_id: int | None,
    message_id: str | None,
    sender_id: str | None = None,
    recipient_id: str | None = None,
    body: str | None = None,
) -> bool:
    key = _build_claim_key(channel, store_id, message_id, sender_id, recipient_id, body)

    redis = await _get_redis()
    if redis:
        try:
            was_new = await redis.set(key, "1", nx=True, ex=_DEDUP_TTL_SECONDS)
            if was_new:
                logger.debug(
                    "webhook_claim new channel=%s store_id=%s msg_id=%s",
                    channel, store_id, message_id,
                )
                return True
            try:
                from services.metrics import webhook_dedup_hits_total
                webhook_dedup_hits_total.labels(channel=channel, outcome="redis").inc()
            except Exception:
                pass
            logger.info(
                "webhook_claim duplicate channel=%s store_id=%s msg_id=%s — skipped",
                channel, store_id, message_id,
            )
            return False
        except Exception as exc:
            logger.warning(
                "webhook_reliability redis_error key=%s — fallback memory: %s",
                key, exc,
            )

    now = time.monotonic()
    if len(_SEEN_MESSAGES) > _MEM_MAX_ENTRIES:
        _mem_purge_expired()

    if key in _SEEN_MESSAGES and _SEEN_MESSAGES[key] > now:
        try:
            from services.metrics import webhook_dedup_hits_total
            webhook_dedup_hits_total.labels(channel=channel, outcome="memory").inc()
        except Exception:
            pass
        logger.info(
            "webhook_claim duplicate (memory) channel=%s store_id=%s msg_id=%s — skipped",
            channel, store_id, message_id,
        )
        return False

    _SEEN_MESSAGES[key] = now + _DEDUP_TTL_SECONDS
    logger.debug(
        "webhook_claim new (memory) channel=%s store_id=%s msg_id=%s",
        channel, store_id, message_id,
    )
    return True


async def release_webhook_claim(
    channel: str,
    store_id: int | None,
    message_id: str,
) -> None:
    key = _build_claim_key(channel, store_id, message_id, None, None, None)

    redis = await _get_redis()
    if redis:
        try:
            await redis.delete(key)
        except Exception as exc:
            logger.warning("release_webhook_claim redis error: %s", exc)

    _SEEN_MESSAGES.pop(key, None)
    logger.info(
        "webhook_claim_released channel=%s store_id=%s msg_id=%s",
        channel, store_id, message_id,
    )


async def get_dedup_stats() -> dict[str, Any]:
    memory_active = sum(1 for exp in _SEEN_MESSAGES.values() if exp > time.monotonic())
    memory_total = len(_SEEN_MESSAGES)

    redis_active: int | None = None
    redis_available = False
    redis = await _get_redis()
    if redis:
        redis_available = True
        try:
            count = await redis.eval(
                f"return #redis.call('keys', '{_REDIS_DEDUP_PREFIX}*')", 0
            )
            redis_active = int(count)
        except Exception:
            pass

    return {
        "redis_available": redis_available,
        "redis_active_claims": redis_active,
        "memory_active_claims": memory_active,
        "memory_total_entries": memory_total,
        "dedup_ttl_seconds": _DEDUP_TTL_SECONDS,
    }
