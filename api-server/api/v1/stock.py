"""api/v1/stock.py — Product catalog + stock management"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.tenant import current_tenant_id
from models.database import Product, get_db
from services.tasks import update_product_embedding

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["Products"])

# CTO audit fix: integration tests use /api/v1/stock/ instead of /api/v1/products/
# and payload fields quantity/sku instead of stock_qty/external_code.
# We keep /products as the primary route but add /stock as a compatible alias.
router_stock_alias = APIRouter(prefix="/stock", tags=["Products (Legacy Alias)"])


# ─── Schemas ──────────────────────────────────────────────────────────────────
class ProductCreateRequest(BaseModel):
    name: str
    description: str | None = None
    price: float
    stock_qty: int = 0
    category: str | None = None
    external_code: str | None = None
    tags: list[str] | None = None
    image_url: str | None = None


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    stock_qty: int | None = None
    category: str | None = None
    tags: list[str] | None = None
    image_url: str | None = None
    is_active: bool | None = None


# ─── List products (public endpoint) ──────────────────────────────────────────
from api.v1._deps import get_store_id as _sid


@router.get("/public", include_in_schema=False, deprecated=True)
async def list_products_public_quarantined(
    store_id: int = Query(..., description="Legacy store ID"),
):
    """Route publique historique conservée en quarantaine.

    La vitrine client utilise exclusivement `/storefront/{store_id}/products`,
    qui applique le contexte tenant, le stock disponible, la pagination curseur
    et le cache. Cette ancienne route reste présente pour éviter une suppression
    brutale, mais elle ne sert plus de catalogue et renvoie explicitement vers
    l’endpoint canonique.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Legacy catalog route quarantined. Use the canonical storefront "
            f"catalog endpoint: /api/v1/storefront/{store_id}/products"
        ),
        headers={
            "X-Deprecated-Route": "true",
            "Link": f'</api/v1/storefront/{store_id}/products>; rel="canonical"',
        },
    )


# ─── List products ────────────────────────────────────────────────────────────
@router.get("/")
@router_stock_alias.get("/", include_in_schema=False)
async def list_products(
    q: str | None = Query(None, description="Search by name/category"),
    category: str | None = None,
    in_stock: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    stmt = select(Product).where(Product.store_id == store_id, Product.is_active)

    if q:
        stmt = stmt.where(
            Product.name.ilike(f"%{q}%") | Product.description.ilike(f"%{q}%")
        )
    if category:
        stmt = stmt.where(Product.category == category)
    if in_stock:
        stmt = stmt.where(Product.stock_qty > 0)

    count_stmt = select(func.count()).select_from(
        stmt.subquery()
    )
    total = (await db.execute(count_stmt)).scalar()

    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    products = result.scalars().all()

    return {
        "items": [_serialize(p) for p in products],
        "total": total,
        "page": page,
    }


# ─── Get single product ───────────────────────────────────────────────────────
@router.get("/{product_id}")
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.store_id == store_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize(product)


# ─── Create product ───────────────────────────────────────────────────────────
@router.post("/", status_code=201)
@router_stock_alias.post("/", status_code=201, include_in_schema=False)
async def create_product(
    request: Request,
    bg: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()

    # Handle both ProductCreateRequest and legacy integration test format
    try:
        raw_body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    if not isinstance(raw_body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")

    # Map legacy fields if present
    if "quantity" in raw_body and "stock_qty" not in raw_body:
        raw_body["stock_qty"] = raw_body.pop("quantity")
    if "sku" in raw_body and "external_code" not in raw_body:
        raw_body["external_code"] = raw_body.pop("sku")

    # Validate with Pydantic — construction manuelle (pas d'injection FastAPI)
    # car on doit remapper les champs legacy avant validation. pydantic.ValidationError
    # n'est pas une HTTPException : sans ce catch, elle tombe dans le handler
    # d'exception générique -> 500 au lieu du 422 attendu par le client.
    try:
        body = ProductCreateRequest(**raw_body)
    except ValidationError as exc:
        # http_exception_handler (main.py) ne préserve exc.detail que s'il
        # s'agit d'une str — sinon il est remplacé par un message générique.
        # On formate donc les erreurs en texte lisible plutôt que de passer
        # la liste de dicts brute de pydantic.
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise HTTPException(status_code=422, detail=detail or "Validation error")
    
    product = Product(store_id=store_id, **body.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)

    # Async embedding generation
    bg.add_task(update_product_embedding.delay, product.id, store_id)

    return _serialize(product)


# ─── Update product ───────────────────────────────────────────────────────────
# CTO audit fix: redirect_slashes=False is set on the app, so /products/{id}/
# (trailing slash) used by Products.jsx wouldn't redirect to /products/{id}.
# Expose both spellings explicitly — same handler.
@router.patch("/{product_id}")
@router.patch("/{product_id}/", include_in_schema=False)
async def update_product(
    product_id: int,
    body: ProductUpdateRequest,
    bg: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.store_id == store_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(product, field, value)

    await db.commit()

    # Re-embed if name/description changed
    if body.name or body.description or body.category or body.tags:
        bg.add_task(update_product_embedding.delay, product.id, store_id)

    return _serialize(product)


# ─── Delete product ───────────────────────────────────────────────────────────
@router.delete("/{product_id}", status_code=204)
@router.delete("/{product_id}/", status_code=204, include_in_schema=False)
async def delete_product(product_id: int, db: AsyncSession = Depends(get_db)):
    store_id = _sid()
    result = await db.execute(
        select(Product).where(Product.id == product_id, Product.store_id == store_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False  # soft delete
    await db.commit()


# ─── Bulk stock update ───────────────────────────────────────────────────────
@router.post("/bulk-stock")
async def bulk_update_stock(
    updates: list[dict],  # [{product_id, stock_qty}]
    db: AsyncSession = Depends(get_db),
):
    store_id = _sid()
    updated = []
    for u in updates:
        result = await db.execute(
            select(Product).where(Product.id == u["product_id"], Product.store_id == store_id)
        )
        p = result.scalar_one_or_none()
        if p:
            p.stock_qty = u["stock_qty"]
            updated.append(p.id)
    await db.commit()
    return {"updated": updated, "count": len(updated)}


# ─── Serializer ──────────────────────────────────────────────────────────────
def _serialize(p: Product) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "stock_qty": p.stock_qty,
        "stock_reserved": getattr(p, "stock_reserved", 0),
        "stock_available": p.stock_qty - getattr(p, "stock_reserved", 0),  # E19: real available qty
        "category": p.category,
        "tags": p.tags,
        "external_code": p.external_code,
        "image_url": p.image_url,
        "is_active": p.is_active,
        "has_embedding": bool(p.embedding),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
