"""services/conversation_memory_service.py — Mémoire Conversationnelle Enterprise.

PHASE 1 — OMNICALL ENTERPRISE
Implémente :
  - mémoire court terme (Redis, TTL 4h)
  - mémoire long terme (PostgreSQL)
  - historique client / commandes / rendez-vous / objections

Architecture :
  ConversationMemoryService
    ├── store_short_term()    -> Redis
    ├── load_short_term()     -> Redis
    ├── store_long_term()     -> PostgreSQL (conversation_memories)
    ├── load_long_term()      -> PostgreSQL
    └── build_memory_context() -> dict enrichi injecté dans le system prompt
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# TTL mémoire court terme (Redis)
SHORT_TERM_TTL_SECONDS = 4 * 3600   # 4 heures
LONG_TERM_MAX_ENTRIES  = 100         # max entrées par client en DB


# ──────────────────────────────────────────────────────────────────────────────
# Helpers Redis
# ──────────────────────────────────────────────────────────────────────────────

def _short_term_key(store_id: int, customer_id: int) -> str:
    return f"mem:st:{store_id}:{customer_id}"


def get_redis():
    """Returns a Redis client instance. Can be patched in tests."""
    from services.redis_lock import get_redis as _get_redis
    return _get_redis()

def _get_redis():
    # Internal wrapper to call the patchable get_redis
    return get_redis()


async def store_short_term(
    store_id: int,
    customer_id: int,
    data: dict[str, Any],
) -> None:
    """Stocke la mémoire court terme dans Redis avec TTL."""
    try:
        r = _get_redis()
        if hasattr(r, "__await__"):
            r = await r
        key = _short_term_key(store_id, customer_id)
        payload = json.dumps(data, ensure_ascii=False, default=str)
        await r.setex(key, SHORT_TERM_TTL_SECONDS, payload)
    except Exception as exc:
        logger.warning("store_short_term failed store=%s customer=%s: %s", store_id, customer_id, exc)


async def load_short_term(store_id: int, customer_id: int) -> dict[str, Any]:
    """Charge la mémoire court terme depuis Redis."""
    try:
        r = _get_redis()
        if hasattr(r, "__await__"):
            r = await r
        key = _short_term_key(store_id, customer_id)
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("load_short_term failed store=%s customer=%s: %s", store_id, customer_id, exc)
    return {}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers PostgreSQL
# ──────────────────────────────────────────────────────────────────────────────

async def store_long_term(
    db,
    store_id: int,
    customer_id: int,
    entry_type: str,         # "message" | "order" | "appointment" | "objection" | "summary"
    content: dict[str, Any],
    source_channel: str = "whatsapp",
) -> None:
    """Persiste une entrée de mémoire long terme en PostgreSQL."""
    try:
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO conversation_memories
                    (store_id, customer_id, entry_type, content, source_channel, created_at)
                VALUES (:store_id, :customer_id, :entry_type, :content::jsonb, :channel, NOW())
            """),
            {
                "store_id": store_id,
                "customer_id": customer_id,
                "entry_type": entry_type,
                "content": json.dumps(content, ensure_ascii=False, default=str),
                "channel": source_channel,
            },
        )
        # Nettoyage FIFO : garder seulement les N dernières entrées par client
        await db.execute(
            text("""
                DELETE FROM conversation_memories
                WHERE store_id = :sid AND customer_id = :cid
                  AND id NOT IN (
                      SELECT id FROM conversation_memories
                      WHERE store_id = :sid AND customer_id = :cid
                      ORDER BY created_at DESC
                      LIMIT :max_entries
                  )
            """),
            {"sid": store_id, "cid": customer_id, "max_entries": LONG_TERM_MAX_ENTRIES},
        )
    except Exception as exc:
        logger.warning("store_long_term failed store=%s customer=%s: %s", store_id, customer_id, exc)


async def load_long_term(
    db,
    store_id: int,
    customer_id: int,
    entry_types: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Charge l'historique long terme depuis PostgreSQL."""
    try:
        from sqlalchemy import text
        # Two static queries — no f-string interpolation into SQL.
        # This eliminates the risk of future accidental injection if a new
        # branch were added that puts user input into the query string.
        if entry_types:
            result = await db.execute(
                text("""
                    SELECT entry_type, content, source_channel, created_at
                    FROM conversation_memories
                    WHERE store_id = :sid AND customer_id = :cid
                      AND entry_type = ANY(:types)
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"sid": store_id, "cid": customer_id, "lim": limit, "types": entry_types},
            )
        else:
            result = await db.execute(
                text("""
                    SELECT entry_type, content, source_channel, created_at
                    FROM conversation_memories
                    WHERE store_id = :sid AND customer_id = :cid
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"sid": store_id, "cid": customer_id, "lim": limit},
            )
        rows = result.mappings().all()
        return [
            {
                "entry_type": r["entry_type"],
                "content": r["content"] if isinstance(r["content"], dict) else json.loads(r["content"] or "{}"),
                "source_channel": r["source_channel"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("load_long_term failed store=%s customer=%s: %s", store_id, customer_id, exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Memory context builder
# ──────────────────────────────────────────────────────────────────────────────

async def build_memory_context(
    db,
    store_id: int,
    customer_id: int,
    customer_phone: str | None = None,
) -> dict[str, Any]:
    """Construit le contexte mémoire complet pour injection dans le system prompt.

    Combine :
      - mémoire court terme (Redis)
      - historique long terme (PostgreSQL) filtré par type

    Retourne un dict avec toutes les clés attendues par OmniCall.
    """
    short_term = await load_short_term(store_id, customer_id)

    history_messages   = await load_long_term(db, store_id, customer_id, ["message"], limit=5)
    history_orders     = await load_long_term(db, store_id, customer_id, ["order"], limit=5)
    history_appts      = await load_long_term(db, store_id, customer_id, ["appointment"], limit=3)
    history_objections = await load_long_term(db, store_id, customer_id, ["objection"], limit=5)
    last_summary       = await load_long_term(db, store_id, customer_id, ["summary"], limit=1)

    return {
        "short_term": short_term,
        "last_messages": [m["content"].get("text", "") for m in history_messages],
        "past_orders": [
            {
                "order_id": o["content"].get("order_id"),
                "total": o["content"].get("total"),
                "status": o["content"].get("status"),
                "date": o["created_at"],
            }
            for o in history_orders
        ],
        "past_appointments": [
            {
                "date": a["content"].get("date"),
                "service": a["content"].get("service"),
            }
            for a in history_appts
        ],
        "past_objections": [o["content"].get("text", "") for o in history_objections],
        "last_conversation_summary": last_summary[0]["content"] if last_summary else None,
        "customer_phone": customer_phone,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers d'enregistrement rapides
# ──────────────────────────────────────────────────────────────────────────────

async def record_message(db, store_id: int, customer_id: int, text: str, direction: str = "in", channel: str = "whatsapp") -> None:
    await store_long_term(db, store_id, customer_id, "message", {"text": text, "direction": direction}, channel)


async def record_order(db, store_id: int, customer_id: int, order_id: int, total: float, status: str) -> None:
    await store_long_term(db, store_id, customer_id, "order", {"order_id": order_id, "total": total, "status": status})


async def record_appointment(db, store_id: int, customer_id: int, date: str, service: str) -> None:
    await store_long_term(db, store_id, customer_id, "appointment", {"date": date, "service": service})


async def record_objection(db, store_id: int, customer_id: int, text: str) -> None:
    await store_long_term(db, store_id, customer_id, "objection", {"text": text})


async def record_summary(db, store_id: int, customer_id: int, summary: dict) -> None:
    await store_long_term(db, store_id, customer_id, "summary", summary)
