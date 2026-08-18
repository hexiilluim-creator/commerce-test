"""services/blueprint_service.py — Application des Blueprints Métier aux stores.

Implémentation production :
  - BlueprintService(db) : instancié avec la session SQLAlchemy async.
  - apply_blueprint_to_store(store, blueprint, custom_config) :
      * Configure store.ai_agent_prompt depuis blueprint.default_ai_prompt
      * Active les modules listés dans blueprint.modules_enabled
      * Applique business_type et service_category
      * Applique les overrides custom_config (surcharge les defaults)
      * Crée les produits/services initiaux si blueprint.initial_data fourni
  - list_blueprints(store_id) -> list[dict] : liste depuis la DB
  - apply_blueprint(store_id, blueprint_id) -> dict : alias haut-niveau

Blueprints supportés : automotive | beauty_salon | guesthouse | restaurant | general_shop
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.blueprints import Blueprint, StoreBlueprint
from models.database import Store

logger = logging.getLogger("blueprint_service")


class BlueprintService:
    """Service d'application des blueprints métier aux stores."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Interface publique ────────────────────────────────────────────────────

    async def list_blueprints(self, store_id: int) -> list[dict[str, Any]]:
        """Retourne la liste de tous les blueprints disponibles.

        Args:
            store_id : Non utilisé, conservé pour compatibilité API.

        Returns:
            Liste de dicts sérialisables (sans lazy-load SQLAlchemy).
        """
        result = await self.db.execute(select(Blueprint).order_by(Blueprint.id))
        blueprints = result.scalars().all()
        return [self._serialize_blueprint(bp) for bp in blueprints]

    async def apply_blueprint(self, store_id: int, blueprint_id: str) -> dict[str, Any]:
        """Applique un blueprint à un store (version simplifiée sans custom_config).

        Args:
            store_id     : ID du store cible.
            blueprint_id : ID du blueprint (ex: "automotive").

        Returns:
            dict avec blueprint_id, applied, modules_enabled, message.

        Raises:
            ValueError : Blueprint introuvable ou store introuvable.
        """
        store = await self.db.get(Store, store_id)
        if not store:
            raise ValueError(f"Store {store_id} introuvable.")

        bp_result = await self.db.execute(
            select(Blueprint).where(Blueprint.id == blueprint_id)
        )
        blueprint = bp_result.scalar_one_or_none()
        if not blueprint:
            raise ValueError(f"Blueprint '{blueprint_id}' introuvable.")

        await self.apply_blueprint_to_store(store, blueprint, custom_config={})
        await self.db.flush()

        return {
            "blueprint_id": blueprint_id,
            "applied": True,
            "modules_enabled": blueprint.modules_enabled or [],
            "message": f"Blueprint '{blueprint.name}' appliqué au store {store_id}.",
        }

    async def apply_blueprint_to_store(
        self,
        store: Store,
        blueprint: Blueprint,
        custom_config: dict[str, Any] | None = None,
    ) -> None:
        """Configure un store selon les paramètres du blueprint.

        Actions effectuées :
          1. Applique le prompt IA par défaut du blueprint (si non customisé).
          2. Configure business_type et service_category.
          3. Enregistre les modules activés dans store.payment_config (champ JSON générique).
          4. Crée les produits/services initiaux si blueprint.initial_data.products fourni.
          5. Applique les surcharges de custom_config (priorité maximale).

        Args:
            store         : Instance ORM Store à modifier.
            blueprint     : Instance ORM Blueprint source.
            custom_config : Surcharges optionnelles (ex: {"ai_agent_prompt": "..."}).
        """
        cfg = custom_config or {}

        # ── 1. Prompt IA ──────────────────────────────────────────────────────
        ai_prompt = cfg.get("ai_agent_prompt") or blueprint.default_ai_prompt
        if ai_prompt and hasattr(store, "ai_agent_prompt"):
            store.ai_agent_prompt = ai_prompt
            logger.debug(
                "apply_blueprint store_id=%d blueprint=%s ai_prompt=%d chars",
                store.id, blueprint.id, len(ai_prompt),
            )

        # ── 2. Type d'activité ────────────────────────────────────────────────
        biz_type = cfg.get("business_type") or blueprint.default_business_type
        if biz_type and hasattr(store, "business_type"):
            store.business_type = biz_type

        svc_cat = cfg.get("service_category") or blueprint.default_service_category
        if svc_cat and hasattr(store, "service_category"):
            store.service_category = svc_cat

        # ── 3. Modules actifs ─────────────────────────────────────────────────
        # Stocké dans store.extra_config (JSON) si disponible, sinon ignoré.
        modules = list(blueprint.modules_enabled or [])
        extra_modules = cfg.get("extra_modules", [])
        if extra_modules:
            modules = list(set(modules + extra_modules))

        if hasattr(store, "extra_config") and store.extra_config is not None:
            extra = dict(store.extra_config)
            extra["blueprint_id"] = blueprint.id
            extra["modules_enabled"] = modules
            store.extra_config = extra
        elif hasattr(store, "extra_config"):
            store.extra_config = {
                "blueprint_id": blueprint.id,
                "modules_enabled": modules,
            }

        # ── 4. Données initiales ──────────────────────────────────────────────
        initial_data = blueprint.initial_data or {}
        initial_products = initial_data.get("products", [])
        if initial_products:
            await self._seed_initial_products(store, initial_products)

        initial_services = initial_data.get("services", [])
        if initial_services:
            await self._seed_initial_services(store, initial_services)

        logger.info(
            "apply_blueprint_to_store store_id=%d blueprint=%s modules=%s",
            store.id, blueprint.id, modules,
        )

    # ── Helpers privés ────────────────────────────────────────────────────────

    async def _seed_initial_products(
        self, store: Store, products: list[dict[str, Any]]
    ) -> None:
        """Crée les produits initiaux définis dans blueprint.initial_data.products.

        Idempotent — ne crée que les produits absents (comparaison par slug).
        """
        try:
            from sqlalchemy import select as sa_select

            from models.database import Product

            for prod_data in products:
                name = prod_data.get("name", "Produit")
                # Vérifie si le produit existe déjà pour ce store
                existing = await self.db.execute(
                    sa_select(Product).where(
                        Product.store_id == store.id,
                        Product.name == name,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                product = Product(
                    store_id=store.id,
                    name=name,
                    description=prod_data.get("description", ""),
                    price=float(prod_data.get("price", 0.0)),
                    stock_qty=int(prod_data.get("stock_qty", 0)),
                    is_active=True,
                    category=prod_data.get("category"),
                )
                self.db.add(product)
                logger.debug(
                    "seed_initial_products store_id=%d product=%s",
                    store.id, name,
                )
        except Exception as exc:
            # Non-bloquant — le blueprint s'applique même si les produits
            # initiaux ne peuvent pas être créés (ex: schéma différent).
            logger.warning(
                "seed_initial_products store_id=%d error=%s",
                store.id, exc,
            )

    async def _seed_initial_services(
        self, store: Store, services: list[dict[str, Any]]
    ) -> None:
        """Crée les services initiaux (rendez-vous, prestations) si table disponible."""
        try:
            from sqlalchemy import select as sa_select

            from models.database import Service  # type: ignore[attr-defined]

            for svc_data in services:
                name = svc_data.get("name", "Service")
                existing = await self.db.execute(
                    sa_select(Service).where(
                        Service.store_id == store.id,
                        Service.name == name,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                service = Service(
                    store_id=store.id,
                    name=name,
                    description=svc_data.get("description", ""),
                    duration_minutes=int(svc_data.get("duration_minutes", 60)),
                    price=float(svc_data.get("price", 0.0)),
                    is_active=True,
                )
                self.db.add(service)
        except (ImportError, AttributeError):
            # Table Service optionnelle selon les migrations
            pass
        except Exception as exc:
            logger.warning("seed_initial_services store_id=%d error=%s", store.id, exc)

    @staticmethod
    def _serialize_blueprint(bp: Blueprint) -> dict[str, Any]:
        """Sérialise un Blueprint ORM en dict JSON-safe."""
        return {
            "id": bp.id,
            "name": bp.name,
            "icon": bp.icon,
            "description": bp.description,
            "modules_enabled": bp.modules_enabled or [],
            "default_ai_prompt": bp.default_ai_prompt,
            "default_business_type": bp.default_business_type,
            "default_service_category": bp.default_service_category,
            "ui_visibility": bp.ui_visibility or {},
            "quotas": bp.quotas or {},
            "initial_data": bp.initial_data or {},
        }
