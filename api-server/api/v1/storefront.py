"""
Endpoints publics pour la vitrine (storefront).
Ces endpoints n'ont pas besoin d'authentification.

P2‑2 — Catalogue paginé + cache Redis 5 min + WebP/AVIF + lazy load (CTO audit).
"""
import base64
import hashlib
import json
import logging
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import Customer, Order, OrderStatus, Product, Store, get_db
from services.promotions_service import apply_promotions_to_items, preview_product_promo_price
from services.tax_service import calculate_taxes_for_items

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/storefront", tags=["Storefront"])


# ─── P2‑2 — Cache + image helpers ─────────────────────────────────────────────
CATALOG_CACHE_TTL_SECONDS = 300          # 5 min — CTO SLA catalogue
CATALOG_CACHE_PREFIX = "storefront:catalog:"


async def _get_redis_safe():
    """Récupère le client Redis asynchrone, fail-open si indisponible."""
    try:
        from lib.redis_client import get_redis as _get_redis
        return await _get_redis()
    except Exception as _e:
        logger.debug("storefront: redis unavailable: %s", _e)
        return None


def _cursor_encode(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + pad).encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _catalog_cache_key(store_id: int, category: str | None, payload: dict) -> str:
    h = hashlib.sha1(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"{CATALOG_CACHE_PREFIX}{store_id}:cat={category or '_'}:h={h}"


async def _cache_get(key: str):
    try:
        r = await _get_redis_safe()
        if r is None:
            return None
        v = await r.get(key)
        if v is None:
            return None
        if isinstance(v, bytes):
            v = v.decode("utf-8")
        return json.loads(v)
    except Exception as _e:
        logger.debug("storefront cache_get failed key=%s: %s", key, _e)
        return None


async def _cache_set(key: str, value, ttl: int = CATALOG_CACHE_TTL_SECONDS):
    try:
        r = await _get_redis_safe()
        if r is None:
            return
        await r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as _e:
        logger.debug("storefront cache_set failed key=%s: %s", key, _e)


async def invalidate_catalog_cache(store_id: int) -> int:
    """À appeler après chaque mutation produit (POST/PUT/DELETE)."""
    try:
        r = await _get_redis_safe()
        if r is None:
            return 0
        removed = 0
        cursor = 0
        pattern = f"{CATALOG_CACHE_PREFIX}{store_id}:*"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                removed += int(await r.delete(*keys) or 0)
            if cursor == 0:
                break
        logger.info("storefront cache invalidated store=%s removed=%s", store_id, removed)
        return removed
    except Exception as _e:
        logger.warning("storefront cache invalidation failed store=%s: %s", store_id, _e)
        return 0


def _image_sources(url: str | None) -> dict:
    """Génère les sources webp/avif + placeholder data: pour lazy-load."""
    placeholder = (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'>"
        "<rect width='1' height='1' fill='%23eef0f4'/></svg>"
    )
    if not url:
        return {"primary": None, "webp": None, "avif": None,
                "lazy_placeholder": placeholder, "loading": "lazy"}
    sep = "&" if "?" in url else "?"
    return {
        "primary": url,
        "webp": f"{url}{sep}fmt=webp",
        "avif": f"{url}{sep}fmt=avif",
        "lazy_placeholder": placeholder,
        "loading": "lazy",
    }


class StorefrontPreviewItem(BaseModel):
    product_id: int | None = None
    name: str
    qty: int = Field(default=1, ge=1)
    unit_price: Decimal = Field(..., ge=0)
    category: str | None = None
    tax_category: str | None = None
    brand: str | None = None
    is_tax_exempt: bool = False


class StorefrontPromotionPreviewRequest(BaseModel):
    items: list[StorefrontPreviewItem]
    coupon_codes: list[str] | None = None
    country_code: str | None = Field(None, min_length=2, max_length=2)
    channel: str | None = Field(default="storefront")
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    event_context: dict | None = None


class StorefrontOrderRequest(BaseModel):
    """Commande publique : les prix envoyés par le navigateur sont ignorés."""

    customer_phone: str = Field(..., min_length=5, max_length=30)
    customer_name: str | None = Field(None, max_length=255)
    customer_email: str | None = Field(None, max_length=320)
    items: list[StorefrontPreviewItem] = Field(..., min_length=1, max_length=100)
    delivery_address: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=2000)
    country_code: str | None = Field("TN", min_length=2, max_length=2)
    coupon_codes: list[str] | None = None


async def _resolve_store(db: AsyncSession, store_id: str):
    """
    FIX: Accept slug or numeric ID.
    Frontend generates /store/{slug} links — storefront must handle both.
    """
    try:
        result = await db.execute(
            select(Store).where(Store.id == int(store_id), Store.is_active)
        )
    except (ValueError, TypeError):
        result = await db.execute(
            select(Store).where(Store.slug == store_id, Store.is_active)
        )
    return result.scalar_one_or_none()


async def _set_public_store_context(db: AsyncSession, store: Store) -> None:
    """Activer le tenant RLS pour une requête storefront anonyme.

    Les tables produit/client/commande sont FORCE RLS. Une route publique ne
    dispose pas du ContextVar d'authentification, mais le store a déjà été
    résolu par slug ou ID ; ce contexte borne donc toutes les requêtes au seul
    tenant demandé sans donner de rôle privilégié.
    """
    await db.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"),
        {"tenant_id": str(store.id)},
    )
    await db.execute(
        text("SELECT set_config('app.current_user_role', 'public', false)")
    )


# ─── Get public store info by ID or slug ────────────────────────────────────
@router.get("/{store_id}")
async def get_storefront(store_id: str, db: AsyncSession = Depends(get_db)):
    """Récupère une boutique par ID numérique ou par slug."""
    store = await _resolve_store(db, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found or inactive")

    return {
        "id": store.id,
        "name": store.name or "Ma Boutique",
        "slug": store.slug,
        "logo_url": getattr(store, "logo_url", None),
        "banner_url": getattr(store, "banner_url", None),
        "description": getattr(store, "description", "Bienvenue dans notre boutique !"),
        "whatsapp_phone": store.whatsapp_phone or "",
        "support_email": getattr(store, "support_email", None),
        "address": getattr(store, "address", None),
        "phone_display": getattr(store, "phone_display", store.whatsapp_phone),
        "website_url": getattr(store, "website_url", None),
        "category": getattr(store, "category", None),
        "opening_hours": getattr(store, "opening_hours", {}),
        "services": getattr(store, "services", []),
        "latitude": getattr(store, "latitude", None),
        "longitude": getattr(store, "longitude", None),
        "social_links": getattr(store, "social_links", {}),
        "language": store.language or "fr",
        "country": getattr(store, "country", None) or "TN",
        "currency": getattr(store, "currency", None) or "TND",
        "timezone": getattr(store, "timezone", None) or "Africa/Tunis",
        "is_open": getattr(store, "is_open", True),
        "is_active": store.is_active,
        "created_at": store.created_at.isoformat() if store.created_at else None,
    }


# ─── P2‑2 — Get public products (cursor pagination + Redis cache) ──────────
@router.get("/{store_id}/products")
async def get_storefront_products(
    store_id: str,
    category: str | None = Query(None, description="Filter by category"),
    cursor: str | None = Query(None, description="Keyset pagination cursor (opaque)"),
    limit: int = Query(12, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
):
    """Liste publique paginée des produits actifs en stock.

    Pagination **keyset** (created_at desc, id desc) stable face aux écritures
    concurrentes. Cache Redis 5 min — invalidé à chaque mutation produit.
    """
    store = await _resolve_store(db, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found or inactive")
    await _set_public_store_context(db, store)

    decoded_cursor = _cursor_decode(cursor) or {}
    last_id = int(decoded_cursor.get("id", 0) or 0)
    last_created = decoded_cursor.get("created_at")

    cache_key = _catalog_cache_key(
        store.id, category,
        {"currency": getattr(store, "currency", None) or "TND", "country": getattr(store, "country", None) or "TN", "cur": decoded_cursor, "lim": limit, "id0": last_id, "ts0": last_created},
    )
    cached = await _cache_get(cache_key)
    if cached:
        cached["cache"] = "HIT"
        return cached

    stmt = select(Product).where(
        Product.store_id == store.id,
        Product.is_active,
        Product.stock_qty > 0,
    )
    if category:
        stmt = stmt.where(Product.category == category)

    # Keyset — comparaison tuple (created_at, id) desc
    if last_id and last_created:
        from sqlalchemy import tuple_
        stmt = stmt.where(
            tuple_(Product.created_at, Product.id) < tuple_(last_created, last_id)
        )

    # limit+1 pour has_more sans second round-trip COUNT
    stmt = stmt.order_by(Product.created_at.desc(), Product.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    has_more = len(rows) > limit
    page = rows[:limit]

    serialized: list[dict] = []
    for p in page:
        promo_price = await preview_product_promo_price(db, store=store, product=p, channel="storefront")
        images = list(p.images) if getattr(p, "images", None) else (
            [p.image_url] if getattr(p, "image_url", None) else []
        )
        images_payload = [_image_sources(u) for u in images]
        serialized.append({
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "price": float(p.price) if p.price else 0.0,
            "promo_price": promo_price,
            "currency": getattr(store, "currency", None) or "TND",
            "images": images_payload,
            "image_url": getattr(p, "image_url", None),
            "category": p.category,
            "stock_qty": p.stock_qty or 0,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    next_cursor = None
    if has_more and page:
        next_cursor = _cursor_encode({
            "id": page[-1].id,
            "created_at": page[-1].created_at.isoformat() if page[-1].created_at else None,
        })

    payload = {
        "products": serialized,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "cache": "MISS",
    }
    await _cache_set(cache_key, payload)
    return payload


@router.post("/{store_id}/orders", status_code=201)
async def create_storefront_order(
    store_id: str,
    body: StorefrontOrderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Créer une commande depuis la vitrine publique.

    Le client ne peut pas imposer le prix : les produits et leurs prix sont
    relus depuis la boutique avant l’application des promotions et des taxes.
    """
    store = await _resolve_store(db, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found or inactive")
    await _set_public_store_context(db, store)

    product_ids = [item.product_id for item in body.items if item.product_id is not None]
    products = list((await db.execute(
        select(Product).where(
            Product.store_id == store.id,
            Product.id.in_(product_ids),
            Product.is_active,
        )
    )).scalars().all())
    products_by_id = {product.id: product for product in products}

    normalized_items: list[dict] = []
    for item in body.items:
        if item.product_id is None or item.product_id not in products_by_id:
            raise HTTPException(status_code=400, detail="Un produit de la commande est indisponible")
        product = products_by_id[item.product_id]
        if (product.stock_qty or 0) <= 0:
            raise HTTPException(status_code=409, detail=f"Produit indisponible: {product.name}")
        if item.qty > (product.stock_qty or 0):
            raise HTTPException(status_code=409, detail=f"Stock insuffisant: {product.name}")
        normalized_items.append({
            "product_id": product.id,
            "name": product.name,
            "qty": item.qty,
            "unit_price": product.price,
            "category": product.category,
            "tax_category": getattr(product, "tax_category", None) or product.category,
            "is_tax_exempt": False,
        })

    customer_result = await db.execute(select(Customer).where(
        Customer.store_id == store.id,
        Customer.whatsapp_phone == body.customer_phone,
    ))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        customer = Customer(
            store_id=store.id,
            whatsapp_phone=body.customer_phone,
            name=body.customer_name,
            channel="storefront",
        )
        db.add(customer)
        await db.flush()
    elif body.customer_name:
        customer.name = body.customer_name

    store_country = (getattr(store, "country", None) or body.country_code or "TN").upper()
    store_currency = (getattr(store, "currency", None) or "TND").upper()

    promotion_result = await apply_promotions_to_items(
        db,
        store=store,
        items=normalized_items,
        coupon_codes=body.coupon_codes,
        country_code=store_country,
        channel="storefront",
        customer_id=customer.id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
    )
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        status=OrderStatus.CONFIRMED,
        channel="storefront",
        # JSONB ne sérialise pas Decimal nativement ; les prix repricés restent
        # Decimal pour les calculs, puis sont encodés au moment de persister.
        items=jsonable_encoder(promotion_result.items),
        total_amount=round(sum(i["qty"] * i["unit_price"] for i in promotion_result.items), 3),
        discount_amount=promotion_result.discount_amount,
        promotion_codes=jsonable_encoder(promotion_result.applied_coupon_codes),
        promotion_breakdown=jsonable_encoder(promotion_result.applied_promotions),
        delivery_name=body.customer_name,
        delivery_address=body.delivery_address,
        notes=body.notes,
    )
    tax_result = await calculate_taxes_for_items(
        db=db,
        store=store,
        items=promotion_result.items,
        country_code=store_country,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
    )
    order.subtotal_amount = tax_result.subtotal_amount
    order.tax_amount = tax_result.tax_amount
    order.country_code = store_country
    order.tax_breakdown = jsonable_encoder(tax_result.breakdown)
    order.currency = store_currency
    order.total_amount = tax_result.total_amount
    db.add(order)
    await db.flush()
    await db.commit()
    # Le contexte RLS public peut être nettoyé par le cycle de commit ; un
    # refresh immédiat relirait alors la ligne hors tenant et provoquerait un
    # faux HTTP 500 après une commande pourtant déjà persistée. expire_on_commit
    # est désactivé dans get_db : les valeurs de l'objet sont disponibles ici.

    return {
        "id": order.id,
        "status": order.status.value if hasattr(order.status, "value") else order.status,
        "channel": order.channel,
        "delivery_name": order.delivery_name,
        "items": order.items,
        "total_amount": float(order.total_amount or 0),
        "currency": order.currency,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


@router.post("/{store_id}/promotions/preview")
async def preview_storefront_promotions(
    store_id: str,
    body: StorefrontPromotionPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    store = await _resolve_store(db, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found or inactive")
    await _set_public_store_context(db, store)

    items = [item.model_dump() for item in body.items]
    promo_result = await apply_promotions_to_items(
        db,
        store=store,
        items=items,
        coupon_codes=body.coupon_codes,
        country_code=body.country_code,
        channel=body.channel,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
        event_context=body.event_context,
    )
    tax_result = await calculate_taxes_for_items(
        db=db,
        store=store,
        items=promo_result.items,
        country_code=body.country_code,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
    )
    return {
        "items": promo_result.items,
        "discount_amount": float(promo_result.discount_amount),
        "applied_promotions": promo_result.applied_promotions,
        "applied_coupon_codes": promo_result.applied_coupon_codes,
        "pricing": tax_result.as_dict(),
    }
