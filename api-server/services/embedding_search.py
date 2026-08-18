"""services/embedding_search.py — Recherche sémantique produits."""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Product
from services.openai_resolver import resolve_openai_client
from services.redis_lock import get_redis

try:
    from pgvector.sqlalchemy import Vector

    PGVECTOR_AVAILABLE = True
except ImportError:
    Vector = None
    PGVECTOR_AVAILABLE = False

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
EMBEDDING_CACHE_TTL_SECONDS = 600


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _read_cached_embedding(cache_key: str) -> list[float] | None:
    try:
        redis_client = get_redis()
        cached = await redis_client.get(cache_key)
        if not cached:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        vector = json.loads(cached)
        if isinstance(vector, list) and len(vector) == EMBEDDING_DIMENSIONS:
            return [float(item) for item in vector]
        logger.warning("embedding_search.invalid_cache_payload key=%s", cache_key)
    except Exception as exc:  # pragma: no cover - best effort cache
        logger.debug("embedding_search.cache_read_failed key=%s error=%s", cache_key, exc)
    return None


async def _write_cached_embedding(cache_key: str, vector: list[float]) -> None:
    try:
        redis_client = get_redis()
        await redis_client.setex(cache_key, EMBEDDING_CACHE_TTL_SECONDS, json.dumps(vector))
    except Exception as exc:  # pragma: no cover - best effort cache
        logger.debug("embedding_search.cache_write_failed key=%s error=%s", cache_key, exc)


def _embedding_cache_key(text_value: str) -> str:
    digest = hashlib.sha256(text_value.encode("utf-8")).hexdigest()[:16]
    return f"emb:{digest}"


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10f}" for value in vector) + "]"


async def embed_query(text: str, store_id: int, db: AsyncSession) -> list[float]:
    """Génère puis cache l'embedding OpenAI d'une requête utilisateur."""
    cache_key = _embedding_cache_key(text)
    cached = await _read_cached_embedding(cache_key)
    if cached is not None:
        return cached

    client = await _maybe_await(resolve_openai_client(store_id, db))
    response = await _maybe_await(
        client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    )

    try:
        vector = list(response.data[0].embedding)
    except Exception as exc:  # pragma: no cover - defensive validation
        raise ValueError("Réponse embedding OpenAI invalide") from exc

    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIMENSIONS}, got {len(vector)}"
        )

    normalized = [float(value) for value in vector]
    await _write_cached_embedding(cache_key, normalized)
    return normalized


async def _search_products_pgvector(
    query: str,
    store_id: int,
    limit: int,
    db: AsyncSession,
) -> list[dict]:
    vector = await embed_query(query, store_id, db)
    sql = text(
        """
        SELECT
            id,
            name,
            price,
            stock_qty,
            category,
            (1 - (embedding <=> :vec)) AS similarity_score
        FROM products
        WHERE store_id = :sid
          AND is_active = true
          AND stock_qty > 0
          AND embedding IS NOT NULL
        ORDER BY embedding <=> :vec
        LIMIT :limit
        """
    )
    params = {
        "sid": store_id,
        "vec": _vector_literal(vector),
        "limit": limit,
    }
    result = await db.execute(sql, params)
    rows = result.mappings().all()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "price": row["price"],
            "stock_qty": row["stock_qty"],
            "category": row["category"],
            "similarity_score": float(row["similarity_score"] or 0.0),
        }
        for row in rows
    ]


async def _search_products_fallback(
    query: str,
    store_id: int,
    limit: int,
    db: AsyncSession,
) -> list[dict]:
    pattern = f"%{query}%"
    stmt = (
        select(Product)
        .where(
            Product.store_id == store_id,
            Product.is_active,
            Product.stock_qty > 0,
            or_(
                Product.name.ilike(pattern),
                Product.description.ilike(pattern),
            ),
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()
    return [
        {
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "stock_qty": product.stock_qty,
            "category": product.category,
            "similarity_score": 1.0,
        }
        for product in products
    ]


async def search_products(
    query: str,
    store_id: int,
    limit: int = 10,
    db: AsyncSession | None = None,
) -> list[dict]:
    if db is None:
        raise ValueError("db session is required")

    if not query or not query.strip() or limit <= 0:
        return []

    dialect_name = getattr(getattr(db, "bind", None), "dialect", None)
    dialect_name = getattr(dialect_name, "name", "")

    if PGVECTOR_AVAILABLE and dialect_name == "postgresql":
        try:
            return await _search_products_pgvector(query, store_id, limit, db)
        except Exception as exc:
            logger.warning("embedding_search.pgvector_failed store_id=%s error=%s", store_id, exc)

    return await _search_products_fallback(query, store_id, limit, db)


async def update_product_embedding(product_id: int, store_id: int, db: AsyncSession) -> None:
    stmt = select(Product).where(Product.id == product_id, Product.store_id == store_id)
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if product is None:
        logger.warning(
            "embedding_search.product_not_found product_id=%s store_id=%s",
            product_id,
            store_id,
        )
        return

    text_to_embed = (
        f"{product.name}. {product.description or ''}. "
        f"Catégorie: {product.category or ''}. Prix: {product.price} TND"
    )
    product.embedding = await embed_query(text_to_embed, store_id, db)
    await db.commit()


async def find_best_match(
    query: str,
    store_id: int,
    limit: int = 5,
    db: AsyncSession | None = None,
) -> list[dict]:
    return await search_products(query=query, store_id=store_id, limit=limit, db=db)
