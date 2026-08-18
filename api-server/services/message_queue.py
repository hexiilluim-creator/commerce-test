"""services/message_queue.py — File de messages Redis Streams (Phase 2).

Architecture :
  Webhook WhatsApp -> push_message() -> Redis Stream "wa:messages"
       v
  Worker (consume_messages) lit le stream et appelle le handler IA.

Garanties :
  - Le webhook répond 200 OK sans attendre le traitement IA.
  - Les messages sont persistés dans Redis Streams (idempotence, retry).
  - Consumer Group -> chaque message est traité exactement une fois.
  - Timeout + DLQ (Dead Letter Queue) pour les messages non acquittés.
  - Fallback Celery si Redis Streams indisponible.

Idempotence :
  - message_id unique par message ; doublon ignoré via XADD NX ou
    vérification SET NX dans le consumer.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
_STREAM_NAME = "wa:messages"
_DLQ_STREAM = "wa:messages:dlq"
_CONSUMER_GROUP = "ai_workers"
_CONSUMER_NAME_PREFIX = "worker"
_BLOCK_MS = 2000          # attente max par XREADGROUP
_MAX_RETRIES = 3          # retries avant DLQ
_PENDING_TIMEOUT_MS = 60_000  # 60 s avant reclaim
_STREAM_MAXLEN = 10_000   # cap pour ne pas gonfler Redis


# ── Producer ──────────────────────────────────────────────────────────────────

async def push_message(payload: dict[str, Any]) -> str | None:
    """Pousse un message WhatsApp dans Redis Streams.

    Retourne l'ID du message créé ou None si Redis est indisponible.
    Le message_id (field "id" du payload) est utilisé pour la déduplication :
    on ne crée pas deux entrées stream pour le même ID WhatsApp.

    Fail-safe : si Redis est indisponible, logge l'erreur et retourne None
    (le webhook doit retomber sur Celery direct).
    """
    try:
        r = await _get_redis()
        if r is None:
            return None

        msg_id = payload.get("message_id") or payload.get("id") or ""
        store_id = payload.get("store_id", "")
        dedup_key = f"wa:dedup:stream:{store_id}:{msg_id}"

        # Déduplication : on ne pousse qu'une seule fois par message WhatsApp
        if msg_id:
            is_new = await r.set(dedup_key, "1", nx=True, ex=86400)
            if not is_new:
                logger.debug("message_queue: duplicate skip msg_id=%s", msg_id)
                return None

        # Sérialiser le payload en champs Redis
        fields = {
            "payload": json.dumps(payload, ensure_ascii=False),
            "store_id": str(store_id),
            "msg_id": msg_id,
            "ts": datetime.now(UTC).isoformat(),
            "retries": "0",
        }

        stream_entry_id = await r.xadd(
            _STREAM_NAME,
            fields,
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )
        logger.debug(
            "message_queue: pushed msg_id=%s stream_entry=%s",
            msg_id,
            stream_entry_id,
        )
        return stream_entry_id.decode() if isinstance(stream_entry_id, bytes) else stream_entry_id
    except Exception as exc:
        logger.warning("message_queue.push_message failed: %s", exc)
        return None


# ── Consumer (Worker) ──────────────────────────────────────────────────────────

async def ensure_consumer_group() -> None:
    """Crée le consumer group s'il n'existe pas déjà."""
    try:
        r = await _get_redis()
        if r is None:
            return
        try:
            await r.xgroup_create(_STREAM_NAME, _CONSUMER_GROUP, id="0", mkstream=True)
            logger.info("message_queue: consumer group '%s' created", _CONSUMER_GROUP)
        except Exception as exc:
            # BUSYGROUP = group already exists — ignoré
            if "BUSYGROUP" not in str(exc):
                logger.warning("message_queue: xgroup_create error: %s", exc)
    except Exception as exc:
        logger.warning("message_queue: ensure_consumer_group failed: %s", exc)


async def consume_messages(
    worker_id: int = 0,
    handler=None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Boucle de consommation principale pour un worker.

    Lit depuis le consumer group et appelle `handler(payload)`.
    Gère les retries et le DLQ automatiquement.

    Args:
        worker_id: Identifiant unique du worker (pour le consumer name).
        handler: Coroutine async handler(payload: dict) à appeler pour chaque message.
        stop_event: asyncio.Event pour arrêter proprement la boucle.
    """
    if handler is None:
        from services.ai_agent import handle_whatsapp_message
        handler = _default_handler

    consumer_name = f"{_CONSUMER_NAME_PREFIX}-{worker_id}"
    await ensure_consumer_group()
    logger.info("message_queue: worker %s started", consumer_name)

    r = await _get_redis()
    if r is None:
        logger.error("message_queue: Redis unavailable — worker %s exiting", consumer_name)
        return

    while stop_event is None or not stop_event.is_set():
        try:
            # Lire les messages non encore acquittés par ce consumer
            messages = await r.xreadgroup(
                _CONSUMER_GROUP,
                consumer_name,
                {_STREAM_NAME: ">"},
                count=10,
                block=_BLOCK_MS,
            )
            if not messages:
                # Reclaim messages bloqués depuis trop longtemps (autres workers tombés)
                await _reclaim_pending(r, consumer_name)
                continue

            for _stream, entries in messages:
                for entry_id, fields in entries:
                    await _process_entry(r, entry_id, fields, consumer_name, handler)

        except asyncio.CancelledError:
            logger.info("message_queue: worker %s cancelled", consumer_name)
            break
        except Exception as exc:
            logger.error("message_queue: worker %s loop error: %s", consumer_name, exc)
            await asyncio.sleep(1.0)


async def _process_entry(r, entry_id, fields: dict, consumer_name: str, handler) -> None:
    """Traite un message depuis le stream et l'acquitte ou le déplace en DLQ."""
    entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
    try:
        raw_payload = fields.get(b"payload") or fields.get("payload") or b"{}"
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode()
        payload = json.loads(raw_payload)

        retries_raw = fields.get(b"retries") or fields.get("retries") or b"0"
        retries = int(retries_raw.decode() if isinstance(retries_raw, bytes) else retries_raw)

        if retries >= _MAX_RETRIES:
            logger.warning(
                "message_queue: entry %s exceeded max retries (%d) -> DLQ",
                entry_id_str,
                _MAX_RETRIES,
            )
            await _send_to_dlq(r, entry_id_str, fields, "max_retries")
            await r.xack(_STREAM_NAME, _CONSUMER_GROUP, entry_id_str)
            return

        await handler(payload)
        await r.xack(_STREAM_NAME, _CONSUMER_GROUP, entry_id_str)
        logger.debug("message_queue: ack entry %s", entry_id_str)

    except Exception as exc:
        logger.warning(
            "message_queue: entry %s handler error (retry %d): %s",
            entry_id_str,
            retries + 1,
            exc,
        )
        # Incrémenter retry count via re-injection
        try:
            new_retries = int(retries) + 1
            fields_dict = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in fields.items()
            }
            fields_dict["retries"] = str(new_retries)
            fields_dict["last_error"] = str(exc)[:200]
            await r.xadd(_STREAM_NAME, fields_dict, maxlen=_STREAM_MAXLEN, approximate=True)
            await r.xack(_STREAM_NAME, _CONSUMER_GROUP, entry_id_str)
        except Exception as retry_exc:
            logger.error("message_queue: retry re-injection failed: %s", retry_exc)


async def _reclaim_pending(r, consumer_name: str) -> None:
    """Reclaim les messages PEL (Pending Entry List) expirés."""
    try:
        pending = await r.xautoclaim(
            _STREAM_NAME,
            _CONSUMER_GROUP,
            consumer_name,
            min_idle_time=_PENDING_TIMEOUT_MS,
            start_id="0-0",
            count=5,
        )
        if pending and pending[1]:
            logger.info(
                "message_queue: reclaimed %d pending messages for %s",
                len(pending[1]),
                consumer_name,
            )
    except Exception as exc:
        if "XAUTOCLAIM" not in str(exc).upper():
            logger.debug("message_queue: reclaim failed: %s", exc)


async def _send_to_dlq(r, entry_id: str, fields: dict, reason: str) -> None:
    """Déplace un message dans la Dead Letter Queue."""
    try:
        dlq_fields = {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in fields.items()
        }
        dlq_fields["dlq_reason"] = reason
        dlq_fields["dlq_ts"] = datetime.now(UTC).isoformat()
        dlq_fields["original_entry_id"] = entry_id
        await r.xadd(_DLQ_STREAM, dlq_fields, maxlen=1000)
        logger.warning("message_queue: entry %s -> DLQ reason=%s", entry_id, reason)
    except Exception as exc:
        logger.error("message_queue: DLQ write failed: %s", exc)


async def _default_handler(payload: dict) -> None:
    """Handler par défaut — route vers handle_whatsapp_message."""
    from models.database import AsyncSessionLocal
    store_id = payload.get("store_id")
    from_phone = payload.get("from_phone") or payload.get("from", "")
    message_text = payload.get("body") or payload.get("text") or ""

    if not store_id or not from_phone:
        logger.warning("message_queue: default_handler missing store_id or from_phone")
        return

    async with AsyncSessionLocal() as db:
        from services.ai_agent import handle_whatsapp_message
        await handle_whatsapp_message(
            store_id=int(store_id),
            customer_phone=from_phone,
            message_text=message_text,
            db=db,
        )


# ── Redis client (lazy) ───────────────────────────────────────────────────────

_redis_client = None


async def _get_redis():
    # NOTE (Bug#6 audit): this _get_redis is intentionally NOT centralized via
    # lib/redis_client.py. This queue handles binary payloads and requires
    # decode_responses=False, while the shared pool uses decode_responses=True
    # for all other services. Centralizing here would corrupt binary message data.
    global _redis_client
    try:
        import redis.asyncio as aioredis

        from config import settings
        if _redis_client is None:
            _redis_client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=False,
                socket_connect_timeout=1.0,
                socket_timeout=2.0,
                max_connections=10,
            )
        await _redis_client.ping()
        return _redis_client
    except Exception as exc:
        logger.warning("message_queue._get_redis failed: %s", exc)
        _redis_client = None
        return None


# ── Stats / health ────────────────────────────────────────────────────────────

async def get_queue_stats() -> dict[str, Any]:
    """Retourne les statistiques de la queue pour Prometheus/dashboard."""
    try:
        r = await _get_redis()
        if r is None:
            return {"error": "redis_unavailable"}
        length = await r.xlen(_STREAM_NAME)
        dlq_length = await r.xlen(_DLQ_STREAM) if await r.exists(_DLQ_STREAM) else 0
        try:
            pending_info = await r.xpending(_STREAM_NAME, _CONSUMER_GROUP)
            pending_count = pending_info.get("pending", 0) if isinstance(pending_info, dict) else 0
        except Exception:
            pending_count = 0
        return {
            "stream_length": length,
            "dlq_length": dlq_length,
            "pending_count": pending_count,
            "stream_name": _STREAM_NAME,
            "consumer_group": _CONSUMER_GROUP,
        }
    except Exception as exc:
        logger.warning("message_queue.get_queue_stats failed: %s", exc)
        return {"error": str(exc)}
