"""
api/v1/social_broadcast.py — API IA Sociale : publication, scheduling, config
==============================================================================

Endpoints :
  GET  /social/broadcast/config           -> config IA du store
  PUT  /social/broadcast/config           -> mettre à jour la config
  POST /social/broadcast/generate         -> générer un post (preview sans publier)
  POST /social/broadcast/publish          -> générer + publier maintenant
  POST /social/broadcast/publish-product  -> publier une fiche produit
  POST /social/broadcast/schedule         -> planifier une publication
  GET  /social/broadcast/posts            -> historique des publications
  GET  /social/broadcast/posts/{id}       -> détail d'un post
  DELETE /social/broadcast/posts/{id}     -> supprimer de l'historique
  GET  /social/broadcast/scheduled        -> publications planifiées
  DELETE /social/broadcast/scheduled/{id} -> annuler une planification
"""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.current_user import current_user_id as _current_user_id
from middleware.tenant import current_tenant_id, current_user_role
from models.database import AuditLog, SocialPost, SocialPostConfig, Store, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social/broadcast", tags=["Social AI Publisher"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class SocialConfigUpdate(BaseModel):
    brand_name: str | None = None
    brand_voice: str = "professionnel"      # professionnel|décontracté|urgent|festif|inspirant
    default_language: str = "fr"
    hashtags: list[str] | None = None
    emoji_style: str = "moderate"           # none|minimal|moderate|expressive
    image_style: str = "commercial product photo, clean background, professional lighting"
    image_colors: str | None = None
    watermark_text: str | None = None
    networks_enabled: list[str] = ["instagram", "facebook"]
    auto_schedule: bool = False
    post_times: list[str] | None = None  # ["09:00", "18:00"]
    post_days: list[int] | None = None   # [0,1,2,3,4] lundi=0
    timezone: str = "Africa/Tunis"
    max_posts_per_day: int = 3


class GenerateRequest(BaseModel):
    topic: str                               # "Promo été 20%", "Nouveau produit: robe bleue"
    networks: list[str] = ["instagram"]
    post_type: str = "post"                  # post|story
    generate_image: bool = True
    custom_caption: str | None = None
    custom_image_url: str | None = None
    extra_context: str | None = None


class PublishRequest(GenerateRequest):
    publish_now: bool = True


class ProductPublishRequest(BaseModel):
    product_id: int
    networks: list[str] = ["instagram", "facebook"]
    post_type: str = "post"
    generate_image: bool = True
    custom_caption: str | None = None
    publish_now: bool = True


class ScheduleRequest(BaseModel):
    topic: str
    networks: list[str]
    post_type: str = "post"
    generate_image: bool = True
    custom_caption: str | None = None
    custom_image_url: str | None = None
    scheduled_at: datetime                   # UTC


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _require_admin():
    if current_user_role.get() != "admin":
        raise HTTPException(403, "Admin role required")


async def _get_store(db: AsyncSession) -> Store:
    store_id = _sid()
    if not store_id:
        raise HTTPException(401, "No tenant context")
    result = await db.execute(select(Store).where(Store.id == store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(404, "Store not found")
    return store


async def _get_config(db: AsyncSession, store_id: int) -> SocialPostConfig | None:
    result = await db.execute(
        select(SocialPostConfig).where(SocialPostConfig.store_id == store_id)
    )
    return result.scalar_one_or_none()


async def _audit(db, store_id, action, detail, request):
    db.add(AuditLog(
        store_id=store_id,
        user_id=_current_user_id.get(),
        action=action,
        resource_type="social_broadcast",
        resource_id=str(store_id),
        detail=detail,
        ip_address=request.client.host if request.client else None,
    ))


def _serialize_post(p: SocialPost) -> dict:
    return {
        "id": p.id,
        "network": p.network,
        "post_type": p.post_type,
        "status": p.status,
        "caption": p.caption,
        "image_url": p.image_url,
        "image_prompt": p.image_prompt,
        "external_post_id": p.external_post_id,
        "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "error": p.error,
        "source": p.source,
        "product_id": p.product_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ─── Config endpoints ─────────────────────────────────────────────────────────

from api.v1._deps import get_store_id as _sid


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    """Récupère la configuration IA sociale du store."""
    store = await _get_store(db)
    config = await _get_config(db, store.id)

    if not config:
        return {
            "configured": False,
            "brand_voice": "professionnel",
            "default_language": "fr",
            "networks_enabled": ["instagram", "facebook"],
            "auto_schedule": False,
            "image_style": "commercial product photo, clean background, professional lighting",
            "emoji_style": "moderate",
            "max_posts_per_day": 3,
            "post_times": ["09:00", "12:00", "18:00"],
            "post_days": [0, 1, 2, 3, 4, 5, 6],
            "timezone": "Africa/Tunis",
        }

    return {
        "configured": True,
        "brand_name": config.brand_name,
        "brand_voice": config.brand_voice,
        "default_language": config.default_language,
        "hashtags": json.loads(config.hashtags or "[]"),
        "emoji_style": config.emoji_style,
        "image_style": config.image_style,
        "image_colors": config.image_colors,
        "watermark_text": config.watermark_text,
        "networks_enabled": json.loads(config.networks_enabled or '["instagram","facebook"]'),
        "auto_schedule": config.auto_schedule,
        "post_times": json.loads(config.post_times or '["09:00","12:00","18:00"]'),
        "post_days": json.loads(config.post_days or '[0,1,2,3,4,5,6]'),
        "timezone": config.timezone,
        "max_posts_per_day": config.max_posts_per_day,
    }


@router.put("/config")
async def update_config(
    body: SocialConfigUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Met à jour la configuration IA sociale (voix, style image, timing)."""
    _require_admin()
    store = await _get_store(db)
    config = await _get_config(db, store.id)

    if not config:
        config = SocialPostConfig(store_id=store.id)
        db.add(config)

    config.brand_name = body.brand_name
    config.brand_voice = body.brand_voice
    config.default_language = body.default_language
    config.hashtags = json.dumps(body.hashtags or [])
    config.emoji_style = body.emoji_style
    config.image_style = body.image_style
    config.image_colors = body.image_colors
    config.watermark_text = body.watermark_text
    config.networks_enabled = json.dumps(body.networks_enabled)
    config.auto_schedule = body.auto_schedule
    config.post_times = json.dumps(body.post_times or ["09:00", "12:00", "18:00"])
    config.post_days = json.dumps(body.post_days if body.post_days is not None else [0,1,2,3,4,5,6])
    config.timezone = body.timezone
    config.max_posts_per_day = body.max_posts_per_day

    await _audit(db, store.id, "social.config.update", {"brand_voice": body.brand_voice, "auto_schedule": body.auto_schedule}, request)
    await db.commit()
    return {"ok": True, "message": "Configuration sauvegardée"}


# ─── Generate (preview) ───────────────────────────────────────────────────────

@router.post("/generate")
async def generate_preview(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Génère caption + image DALL-E sans publier.
    Permet de prévisualiser avant publication.
    """
    _require_admin()
    store = await _get_store(db)
    config = await _get_config(db, store.id)

    from services.social_publisher import generate_caption, generate_image_dalle

    # Générer caption
    caption = body.custom_caption or await generate_caption(
        topic=body.topic,
        network=body.networks[0] if body.networks else "instagram",
        post_type=body.post_type,
        config=config,
        store_name=store.name or "Boutique",
        extra_context=body.extra_context or "",
    )

    # Générer image
    image_url, image_prompt, dalle_error = None, None, None
    if body.generate_image and not body.custom_image_url:
        try:
            image_url, image_prompt = await generate_image_dalle(body.topic, config)
        except Exception as e:
            dalle_error = str(e)
    elif body.custom_image_url:
        image_url = body.custom_image_url

    return {
        "ok": True,
        "mode": "preview",
        "caption": caption,
        "image_url": image_url,
        "image_prompt": image_prompt,
        "dalle_error": dalle_error,
        "networks": body.networks,
        "post_type": body.post_type,
    }


# ─── Publish now ─────────────────────────────────────────────────────────────

@router.post("/publish")
async def publish_now(
    body: PublishRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Génère (GPT + DALL-E) et publie immédiatement sur les réseaux sélectionnés.
    """
    _require_admin()
    store = await _get_store(db)
    config = await _get_config(db, store.id)

    if not body.networks:
        raise HTTPException(400, "Sélectionnez au moins un réseau")

    from services.social_publisher import run_publish_pipeline
    result = await run_publish_pipeline(
        db=db,
        store=store,
        config=config,
        topic=body.topic,
        networks=body.networks,
        post_type=body.post_type,
        generate_image=body.generate_image,
        custom_caption=body.custom_caption,
        custom_image_url=body.custom_image_url,
        source="manual",
        extra_context=body.extra_context or "",
    )

    await _audit(db, store.id, "social.broadcast.publish", {
        "topic": body.topic[:100], "networks": body.networks,
        "published": result["published"], "failed": result["failed"],
    }, request)
    await db.commit()
    return result


# ─── Publish product ─────────────────────────────────────────────────────────

@router.post("/publish-product")
async def publish_product(
    body: ProductPublishRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Publie automatiquement une fiche produit du catalogue.
    L'IA génère caption + image DALL-E basés sur le produit.
    """
    _require_admin()
    store = await _get_store(db)
    config = await _get_config(db, store.id)

    from models.database import Product
    prod = (await db.execute(
        select(Product).where(Product.id == body.product_id, Product.store_id == store.id)
    )).scalar_one_or_none()
    if not prod:
        raise HTTPException(404, "Produit introuvable")

    # Construire le topic depuis les infos produit
    price_hint = f", prix {prod.price:.2f} DT" if prod.price else ""
    topic = f"{prod.name}{price_hint}"
    extra = prod.description[:200] if prod.description else ""

    # Image produit existante ou DALL-E
    custom_image = None
    if not body.generate_image and prod.images:
        imgs = prod.images if isinstance(prod.images, list) else []
        custom_image = imgs[0] if imgs and isinstance(imgs[0], str) else None

    from services.social_publisher import run_publish_pipeline
    result = await run_publish_pipeline(
        db=db,
        store=store,
        config=config,
        topic=topic,
        networks=body.networks,
        post_type=body.post_type,
        generate_image=body.generate_image,
        custom_caption=body.custom_caption,
        custom_image_url=custom_image,
        product_id=prod.id,
        source="product",
        extra_context=extra,
    )

    await _audit(db, store.id, "social.broadcast.product", {
        "product_id": prod.id, "product_name": prod.name,
        "networks": body.networks, "published": result["published"],
    }, request)
    await db.commit()
    return {**result, "product": {"id": prod.id, "name": prod.name}}


# ─── Schedule ────────────────────────────────────────────────────────────────

@router.post("/schedule")
async def schedule_post(
    body: ScheduleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Planifie une publication à une date/heure précise."""
    _require_admin()
    store = await _get_store(db)
    config = await _get_config(db, store.id)

    now = datetime.now(UTC)
    if body.scheduled_at.replace(tzinfo=UTC) <= now:
        raise HTTPException(400, "La date doit être dans le futur")

    delay = int((body.scheduled_at.replace(tzinfo=UTC) - now).total_seconds())

    # Pré-générer caption maintenant (pas au moment de la pub)
    from services.social_publisher import generate_caption, generate_image_dalle
    caption = body.custom_caption or await generate_caption(
        topic=body.topic,
        network=body.networks[0] if body.networks else "instagram",
        post_type=body.post_type,
        config=config,
        store_name=store.name or "Boutique",
    )

    image_url = body.custom_image_url
    image_prompt = None
    if body.generate_image and not image_url:
        try:
            image_url, image_prompt = await generate_image_dalle(body.topic, config)
        except Exception as e:
            logger.warning(f"DALL-E pre-gen failed for schedule: {e}")

    # Créer les entrées DB avec status=scheduled
    post_ids = []
    task_id = None
    for network in body.networks:
        post = SocialPost(
            store_id=store.id,
            network=network,
            post_type=body.post_type,
            status="scheduled",
            caption=caption,
            image_url=image_url,
            image_prompt=image_prompt,
            scheduled_at=body.scheduled_at,
            source="scheduled",
        )
        db.add(post)
        await db.flush()
        post_ids.append(post.id)

    # Lancer la tâche Celery
    try:
        from services.tasks import execute_scheduled_social_posts
        task = execute_scheduled_social_posts.apply_async(
            args=[store.id, post_ids],
            countdown=delay,
        )
        task_id = task.id
        # Single UPDATE instead of N individual SELECT+UPDATE (N+1 fix)
        from sqlalchemy import update as _sa_update
        await db.execute(
            _sa_update(SocialPost)
            .where(SocialPost.id.in_(post_ids))
            .values(celery_task_id=task_id)
        )
    except Exception as e:
        logger.error(f"Celery schedule failed: {e}")

    await _audit(db, store.id, "social.broadcast.schedule", {
        "topic": body.topic[:100], "networks": body.networks,
        "scheduled_at": body.scheduled_at.isoformat(),
    }, request)
    await db.commit()

    return {
        "ok": True,
        "post_ids": post_ids,
        "celery_task_id": task_id,
        "scheduled_at": body.scheduled_at.isoformat(),
        "caption_preview": caption[:150],
        "image_url": image_url,
        "networks": body.networks,
    }


# ─── History ─────────────────────────────────────────────────────────────────

@router.get("/posts")
async def list_posts(
    status: str | None = None,
    network: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Historique des publications (publiées, planifiées, échouées)."""
    store = await _get_store(db)
    q = select(SocialPost).where(SocialPost.store_id == store.id)
    if status:
        q = q.where(SocialPost.status == status)
    if network:
        q = q.where(SocialPost.network == network)
    q = q.order_by(SocialPost.created_at.desc()).limit(limit).offset(offset)
    posts = (await db.execute(q)).scalars().all()
    return [_serialize_post(p) for p in posts]


@router.get("/posts/{post_id}")
async def get_post(post_id: int, db: AsyncSession = Depends(get_db)):
    store = await _get_store(db)
    p = (await db.execute(
        select(SocialPost).where(SocialPost.id == post_id, SocialPost.store_id == store.id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Post introuvable")
    return _serialize_post(p)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, db: AsyncSession = Depends(get_db)):
    _require_admin()
    store = await _get_store(db)
    p = (await db.execute(
        select(SocialPost).where(SocialPost.id == post_id, SocialPost.store_id == store.id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Post introuvable")
    await db.delete(p)
    await db.commit()


@router.get("/scheduled")
async def list_scheduled(db: AsyncSession = Depends(get_db)):
    """Publications planifiées non encore publiées."""
    store = await _get_store(db)
    now = datetime.now(UTC)
    posts = (await db.execute(
        select(SocialPost).where(
            SocialPost.store_id == store.id,
            SocialPost.status == "scheduled",
            SocialPost.scheduled_at > now,
        ).order_by(SocialPost.scheduled_at.asc())
    )).scalars().all()
    return [_serialize_post(p) for p in posts]


@router.delete("/scheduled/{post_id}", status_code=204)
async def cancel_scheduled(post_id: int, db: AsyncSession = Depends(get_db)):
    """Annule une publication planifiée."""
    _require_admin()
    store = await _get_store(db)
    p = (await db.execute(
        select(SocialPost).where(
            SocialPost.id == post_id,
            SocialPost.store_id == store.id,
            SocialPost.status == "scheduled",
        )
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Publication planifiée introuvable")

    # Révoquer la tâche Celery
    if p.celery_task_id:
        try:
            from services.celery_app import celery_app
            celery_app.control.revoke(p.celery_task_id, terminate=True)
        except Exception as _exc:
            logger.warning("cancel_scheduled failed: %s", _exc)
            pass

    p.status = "cancelled"
    await db.commit()
