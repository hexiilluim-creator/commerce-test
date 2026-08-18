"""
api/v1/blueprints.py — Endpoints pour la gestion des Blueprints Métier
========================================================================
Routes:
  GET    /api/v1/blueprints/           -> liste tous les blueprints disponibles
  GET    /api/v1/blueprints/{id}       -> détail d'un blueprint
  GET    /api/v1/blueprints/my-store   -> blueprint sélectionné pour le store actuel
  POST   /api/v1/blueprints/select     -> sélectionner un blueprint pour le store
  PUT    /api/v1/blueprints/customize  -> personnaliser la config du blueprint
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.auth import get_current_store
from models.blueprints import Blueprint, BlueprintRead, StoreBlueprint, StoreBlueprintRead, StoreBlueprintSelect
from models.database import Store, get_db
from services.blueprint_service import BlueprintService

router = APIRouter(prefix="/blueprints", tags=["blueprints"])


# ─── Endpoints publics (liste des blueprints) ─────────────────────────────


@router.get("/", response_model=list[BlueprintRead])
async def list_blueprints(db: AsyncSession = Depends(get_db)):
    """
    Liste tous les blueprints disponibles.
    Endpoint public (pas besoin d'authentification).
    """
    result = await db.execute(select(Blueprint).order_by(Blueprint.id))
    blueprints = result.scalars().all()
    return blueprints

@router.get("/my-store", response_model=StoreBlueprintRead | None)
async def get_my_blueprint(
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    """
    Récupère le blueprint sélectionné pour le store actuel.
    Retourne None si aucun blueprint n'a encore été sélectionné.
    """
    result = await db.execute(
        select(StoreBlueprint).where(StoreBlueprint.store_id == store.id)
    )
    store_blueprint = result.scalar_one_or_none()
    return store_blueprint

@router.post("/select", response_model=StoreBlueprintRead, status_code=status.HTTP_201_CREATED)
async def select_blueprint(
    body: StoreBlueprintSelect,
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    """
    Sélectionne un blueprint pour le store actuel.
    Crée ou met à jour la liaison StoreBlueprint.
    """
    # Vérifier que le blueprint existe
    blueprint_result = await db.execute(
        select(Blueprint).where(Blueprint.id == body.blueprint_id)
    )
    blueprint = blueprint_result.scalar_one_or_none()
    if not blueprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blueprint non trouvé")

    # Chercher si une liaison existe déjà
    existing_result = await db.execute(
        select(StoreBlueprint).where(StoreBlueprint.store_id == store.id)
    )
    store_blueprint = existing_result.scalar_one_or_none()

    if store_blueprint:
        # Mise à jour
        store_blueprint.blueprint_id = body.blueprint_id
        store_blueprint.custom_config = body.custom_config or {}
    else:
        # Création
        store_blueprint = StoreBlueprint(
            store_id=store.id,
            blueprint_id=body.blueprint_id,
            custom_config=body.custom_config or {},
        )
        db.add(store_blueprint)

    # Appliquer les configurations du blueprint au store
    service = BlueprintService(db)
    await service.apply_blueprint_to_store(store, blueprint, store_blueprint.custom_config)

    await db.commit()
    await db.refresh(store_blueprint)
    return store_blueprint

@router.put("/customize", response_model=StoreBlueprintRead)
async def customize_blueprint(
    body: dict,  # Contient la config personnalisée à fusionner
    store: Store = Depends(get_current_store),
    db: AsyncSession = Depends(get_db),
):
    """
    Personnalise la configuration du blueprint pour le store.
    Fusionne les valeurs fournies avec la config existante.
    """
    result = await db.execute(
        select(StoreBlueprint).where(StoreBlueprint.store_id == store.id)
    )
    store_blueprint = result.scalar_one_or_none()
    if not store_blueprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun blueprint sélectionné pour ce store"
        )

    # Fusionner les configs
    store_blueprint.custom_config = {**store_blueprint.custom_config, **body}
    await db.commit()
    await db.refresh(store_blueprint)
    return store_blueprint

@router.get("/{blueprint_id}", response_model=BlueprintRead)
async def get_blueprint(blueprint_id: str, db: AsyncSession = Depends(get_db)):
    """
    Récupère les détails d'un blueprint spécifique.
    """
    result = await db.execute(select(Blueprint).where(Blueprint.id == blueprint_id))
    blueprint = result.scalar_one_or_none()
    if not blueprint:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blueprint non trouvé")
    return blueprint


# ─── Endpoints authentifiés (gestion du blueprint du store) ────────────────
