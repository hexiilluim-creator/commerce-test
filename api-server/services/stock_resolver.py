"""services/stock_resolver.py — Résolution du stock pièces auto.

Sources de stock (par ordre) :
  1. Catalogue produits local (table `products`, filtrage OEM ref + keywords).
  2. API stock externe (Store.stock_api_url + Store.stock_api_key_enc) si configurée.

Interface publique :
  StockItem                           — dataclass produit en stock
  resolve_stock(db, store, oem_refs, part_kws, vehicle_kws) -> list[StockItem]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import String, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Product, Store

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 8.0


# ── Dataclass résultat ────────────────────────────────────────────────────────

@dataclass
class StockItem:
    """Pièce disponible en stock."""
    name:        str
    reference:   str | None
    price:       float
    stock_qty:   int
    source:      str = "local"     # "local" | "external"
    image_url:   str | None = None
    product_id:  int | None = None

    def is_in_stock(self) -> bool:
        return self.stock_qty > 0

    def format_wa(self) -> str:
        """Formate l'item pour un message WhatsApp."""
        stock_badge = "✅" if self.is_in_stock() else "⚠️ Sur commande"
        ref_str = f" `{self.reference}`" if self.reference else ""
        return f"• *{self.name}*{ref_str} — {self.price:.3f} DT {stock_badge} ({self.stock_qty} en stock)"


# ── Recherche locale (table products) ────────────────────────────────────────

async def _search_local_stock(
    db: AsyncSession,
    store_id: int,
    oem_refs: list[str],
    part_kws: list[str],
    vehicle_kws: list[str],
    limit: int = 8,
) -> list[StockItem]:
    """Recherche dans le catalogue produits local du tenant.

    Stratégie :
      1. Correspondance exacte sur external_code (= référence OEM cataloguée).
      2. Correspondance textuelle (name ILIKE) sur références OEM + keywords.
      3. Correspondance textuelle sur tags JSON (contains).
    """
    conditions = []

    # 1. Références OEM exactes
    for ref in oem_refs:
        conditions.append(Product.external_code == ref)

    # 2. Nom contient référence OEM ou keyword pièce
    search_terms = oem_refs + part_kws
    for term in search_terms[:6]:  # Limiter pour éviter une clause WHERE trop large
        if len(term) >= 3:
            conditions.append(Product.name.ilike(f"%{term}%"))
            if Product.description is not None:
                conditions.append(Product.description.ilike(f"%{term}%"))

    # 3. Keywords véhicule dans les tags
    # AUDIT FIX : .cast(str) passait le type Python natif `str` à SQLAlchemy
    # .cast(), qui exige un TypeEngine (sqlalchemy.String). Provoquait un
    # TypeError: "Object '' associated with '.type' attribute is not a
    # TypeEngine class or object".
    for vkw in vehicle_kws[:3]:
        if len(vkw) >= 3:
            conditions.append(Product.tags.cast(String).ilike(f"%{vkw}%"))

    if not conditions:
        return []

    stmt = (
        select(Product)
        .where(Product.store_id == store_id)
        .where(or_(*conditions))
        .order_by(
            # Priorité : en stock d'abord
            (Product.stock_qty > 0).desc(),
            Product.price.asc(),
        )
        .limit(limit)
    )

    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as exc:
        logger.error("Local stock search failed: %s", exc)
        return []

    items = []
    for p in rows:
        items.append(StockItem(
            name=p.name,
            reference=p.external_code,
            price=float(p.price),
            stock_qty=max(0, p.stock_qty - (p.stock_reserved or 0)),
            source="local",
            image_url=p.image_url,
            product_id=p.id,
        ))

    return items


# ── API Stock externe ─────────────────────────────────────────────────────────

async def _search_external_stock(
    store: Store,
    oem_refs: list[str],
    part_kws: list[str],
) -> list[StockItem]:
    """Interroge l'API stock externe configurée sur le Store.

    Format attendu de l'API (GET /search?q=...&refs=...) :
    {
      "items": [
        {
          "name": "...",
          "reference": "...",
          "price": 45.000,
          "stock": 3,
          "image_url": "..."   // optionnel
        }
      ]
    }
    """
    stock_url = getattr(store, "stock_api_url", None)
    stock_key_enc = getattr(store, "stock_api_key_enc", None)

    if not stock_url:
        return []

    # AUDIT FIX (CRITICAL, SSRF) : stock_url est configurée par le marchand
    # lui-même et appelée automatiquement par l'agent IA à chaque recherche
    # de pièce, avec le corps de réponse renvoyé tel quel dans la conversation
    # client. Sans validation, un tenant peut faire pointer cette URL vers le
    # réseau interne (métadonnées cloud, Redis, etc.) et en exfiltrer le
    # contenu directement dans le chat.
    from services.ssrf_guard import SSRFBlocked, assert_safe_external_url
    try:
        assert_safe_external_url(stock_url)
    except SSRFBlocked as exc:
        logger.warning("stock_resolver: stock_api_url bloquée (SSRF guard) store_id=%s: %s", store.id, exc)
        return []

    # Déchiffrer la clé
    api_key: str | None = None
    if stock_key_enc:
        try:
            from config import settings
            api_key = settings.decrypt(stock_key_enc)
        except Exception as exc:
            logger.warning("Failed to decrypt stock_api_key: %s", exc)

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    params: dict[str, str] = {}
    if oem_refs:
        params["refs"] = ",".join(oem_refs[:5])
    if part_kws:
        params["q"] = " ".join(part_kws[:4])

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{stock_url.rstrip('/')}/search",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        items = []
        for raw in data.get("items", [])[:8]:
            items.append(StockItem(
                name=raw.get("name", "Pièce"),
                reference=raw.get("reference"),
                price=float(raw.get("price", 0.0)),
                stock_qty=int(raw.get("stock", 0)),
                source="external",
                image_url=raw.get("image_url"),
            ))
        return items

    except httpx.HTTPStatusError as exc:
        logger.warning("External stock API HTTP %s: %s", exc.response.status_code, exc)
        return []
    except Exception as exc:
        logger.warning("External stock API failed: %s", exc)
        return []


# ── Point d'entrée principal ──────────────────────────────────────────────────

async def resolve_stock(
    db: AsyncSession,
    store: Store,
    oem_refs: list[str],
    part_kws: list[str],
    vehicle_kws: list[str],
) -> list[StockItem]:
    """Résout le stock disponible pour une demande de pièce auto.

    Interroge d'abord le stock local, puis l'API externe si configurée.
    Les résultats sont déduplicés sur la référence et triés (en stock d'abord).

    Args:
        db          : Session SQLAlchemy async.
        store       : Store tenant courant.
        oem_refs    : Références OEM à rechercher (ex: ["7700274176", "7700598565"]).
        part_kws    : Keywords de la pièce (ex: ["filtre", "huile"]).
        vehicle_kws : Keywords du véhicule (ex: ["Renault", "Clio", "2015"]).

    Returns:
        Liste de StockItem triée par disponibilité puis prix, max 8 items.
    """
    # 1. Stock local
    local_items = await _search_local_stock(
        db, store.id, oem_refs, part_kws, vehicle_kws
    )

    # 2. API externe (si configurée et stock local insuffisant)
    external_items: list[StockItem] = []
    if len(local_items) < 3:  # Compléter si peu de résultats locaux
        external_items = await _search_external_stock(store, oem_refs, part_kws)

    # 3. Fusion et déduplication sur référence
    seen_refs: set[str] = set()
    merged: list[StockItem] = []

    for item in local_items + external_items:
        key = item.reference or item.name.lower()
        if key not in seen_refs:
            seen_refs.add(key)
            merged.append(item)

    # 4. Tri : en stock d'abord, puis par prix
    merged.sort(key=lambda i: (0 if i.is_in_stock() else 1, i.price))

    result = merged[:8]
    logger.info(
        "resolve_stock store=%d: %d local + %d external = %d merged results",
        store.id, len(local_items), len(external_items), len(result),
    )
    return result
