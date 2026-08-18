"""
api/v1/product_images.py — Product Image Upload & Management (V19.2)
=====================================================================

Endpoints pour gérer les images des produits :
  - POST   /api/v1/products/{product_id}/images — Upload une nouvelle image
  - DELETE /api/v1/products/{product_id}/images/{image_index} — Supprime une image
  - GET    /api/v1/products/{product_id}/images — Liste les images du produit

Respect des quotas par plan d'abonnement (1-5 images par produit).
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth import _get_current_user_from_request
from models.database import Product, Store, get_db
from services.saas_billing import get_plan_by_code
from services.upload_security import UploadRejected, validate_and_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["product_images"])


@router.post("/{product_id}/images")
async def upload_product_image(
    request: Request,
    product_id: int = Path(..., gt=0),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload une image pour un produit.
    
    Validations :
    - L'utilisateur doit avoir accès au produit (store_id matching)
    - Le nombre d'images actuelles doit être < quota du plan
    - Le fichier doit être une image valide (jpg, png, webp, gif)
    - Taille max : 5 MB
    
    Retourne : { "url": "...", "image_count": 2, "quota": 3 }
    """
    # 1. Authentification
    user = await _get_current_user_from_request(request, db)
    
    # 2. Récupération du produit
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Vérification d'accès (multi-tenant)
    if product.store_id != user.store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 3. Récupération du plan et du quota
    store = await db.get(Store, user.store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
    plan = await get_plan_by_code(db, store.billing_plan_code)
    # BUG FIX (confirmé en déploiement réel — 2026-07-02):
    # get_plan_by_code() retourne dict | None (jamais un objet avec attribut).
    # Code précédent: plan.features_json.get(...) -> AttributeError garanti,
    # que plan soit None (NoneType) ou un dict valide (dict n'a pas
    # d'attribut features_json, seulement une clé). Fallback à 1 image
    # si aucun plan n'est résolu, plutôt que de faire planter l'upload.
    features = (plan or {}).get("features_json") or {}
    max_images = features.get("max_product_images_per_product", 1)
    
    # 4. Vérification du quota
    current_count = product.image_count or 0
    if current_count >= max_images:
        raise HTTPException(
            status_code=403,
            detail=f"Image quota exceeded. Max {max_images} images per product for your plan.",
        )
    
    # 5. Validation et stockage du fichier
    try:
        file_data = await file.read()
        stored = await validate_and_store(
            data=file_data,
            filename=file.filename,
            content_type=file.content_type,
            tenant_id=user.store_id,
            allow="image",
            max_bytes=5 * 1024 * 1024,  # 5 MB
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=f"Upload rejected: {exc}") from exc
    except Exception as exc:
        logger.error(f"Upload failed: {exc}")
        raise HTTPException(status_code=500, detail="Upload failed") from exc
    
    # 6. Mise à jour du produit
    if not product.images:
        product.images = []
    product.images.append(stored["url"])
    product.image_count = len(product.images)
    
    # Fallback : si image_url est vide, utiliser la première image
    if not product.image_url:
        product.image_url = stored["url"]
    
    db.add(product)
    await db.flush()
    
    logger.info(
        "Product image uploaded",
        extra={
            "product_id": product_id,
            "store_id": user.store_id,
            "image_count": product.image_count,
            "storage_key": stored["storage_key"],
        },
    )
    
    return {
        "url": stored["url"],
        "image_count": product.image_count,
        "quota": max_images,
        "storage_backend": stored["storage_backend"],
    }


@router.delete("/{product_id}/images/{image_index}")
async def delete_product_image(
    request: Request,
    product_id: int = Path(..., gt=0),
    image_index: int = Path(..., ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Supprime une image d'un produit par son index.
    
    Validations :
    - L'utilisateur doit avoir accès au produit (store_id matching)
    - L'index doit être valide (0 <= index < len(images))
    
    Retourne : { "image_count": 1, "quota": 3 }
    """
    # 1. Authentification
    user = await _get_current_user_from_request(request, db)
    
    # 2. Récupération du produit
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Vérification d'accès (multi-tenant)
    if product.store_id != user.store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 3. Vérification de l'index
    if not product.images or image_index >= len(product.images):
        raise HTTPException(status_code=400, detail="Invalid image index")
    
    # 4. Suppression de l'image
    deleted_url = product.images.pop(image_index)
    product.image_count = len(product.images)
    
    # Si on supprime l'image_url principale, utiliser la première image restante
    if product.image_url == deleted_url:
        product.image_url = product.images[0] if product.images else None
    
    db.add(product)
    await db.flush()
    
    logger.info(
        "Product image deleted",
        extra={
            "product_id": product_id,
            "store_id": user.store_id,
            "image_index": image_index,
            "image_count": product.image_count,
        },
    )
    
    # Récupération du plan pour le quota
    store = await db.get(Store, user.store_id)
    plan = await get_plan_by_code(db, store.billing_plan_code)
    # BUG FIX (confirmé en déploiement réel — 2026-07-02):
    # get_plan_by_code() retourne dict | None (jamais un objet avec attribut).
    # Code précédent: plan.features_json.get(...) -> AttributeError garanti,
    # que plan soit None (NoneType) ou un dict valide (dict n'a pas
    # d'attribut features_json, seulement une clé). Fallback à 1 image
    # si aucun plan n'est résolu, plutôt que de faire planter l'upload.
    features = (plan or {}).get("features_json") or {}
    max_images = features.get("max_product_images_per_product", 1)
    
    return {
        "image_count": product.image_count,
        "quota": max_images,
    }


@router.get("/{product_id}/images")
async def list_product_images(
    request: Request,
    product_id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Liste les images d'un produit avec les métadonnées de quota.
    
    Retourne : { "images": [...], "image_count": 2, "quota": 3 }
    """
    # 1. Authentification
    user = await _get_current_user_from_request(request, db)
    
    # 2. Récupération du produit
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Vérification d'accès (multi-tenant)
    if product.store_id != user.store_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 3. Récupération du plan pour le quota
    store = await db.get(Store, user.store_id)
    plan = await get_plan_by_code(db, store.billing_plan_code)
    # BUG FIX (confirmé en déploiement réel — 2026-07-02):
    # get_plan_by_code() retourne dict | None (jamais un objet avec attribut).
    # Code précédent: plan.features_json.get(...) -> AttributeError garanti,
    # que plan soit None (NoneType) ou un dict valide (dict n'a pas
    # d'attribut features_json, seulement une clé). Fallback à 1 image
    # si aucun plan n'est résolu, plutôt que de faire planter l'upload.
    features = (plan or {}).get("features_json") or {}
    max_images = features.get("max_product_images_per_product", 1)
    
    return {
        "images": product.images or [],
        "image_count": product.image_count or 0,
        "quota": max_images,
        "legacy_image_url": product.image_url,  # Pour backward compatibility
    }
