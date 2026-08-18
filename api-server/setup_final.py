"""setup_final.py — Initialisation de la base de données en production.

Usage :
    python setup_final.py

Variables d'environnement requises (définir dans .env ou dans le shell) :
    DATABASE_URL           — Chaîne de connexion PostgreSQL async (obligatoire)
    ADMIN_EMAIL            — Email du compte super_admin initial (obligatoire)
    ADMIN_INITIAL_PASSWORD — Mot de passe du compte super_admin initial (obligatoire)

Ces variables NE DOIVENT JAMAIS être hardcodées dans ce fichier.
En production, les injecter via les secrets Doppler / Vault / Railway / Render.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.v1.auth import hash_password
from models.database import Store, User
from services.saas_billing import ensure_default_saas_plans

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("setup_final")



def _require_env(var: str) -> str:
    """Lit une variable d'environnement obligatoire et lève une erreur explicite si absente."""
    value = os.environ.get(var, "").strip()
    if not value:
        logger.error(
            "Variable d'environnement manquante : %s\n"
            "Définissez-la avant de lancer setup_final.py :\n"
            "  export %s=<valeur>",
            var,
            var,
        )
        sys.exit(1)
    return value


async def setup() -> None:
    from config import settings

    # ── Lecture des variables d'environnement obligatoires ────────────────────
    # Ne jamais hardcoder ces valeurs. Les définir via :
    #   - Variables d'environnement shell
    #   - Fichier .env chargé par python-dotenv
    #   - Secrets manager (Doppler, HashiCorp Vault, etc.)
    admin_email: str = _require_env("ADMIN_EMAIL")
    admin_password: str = _require_env("ADMIN_INITIAL_PASSWORD")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        # ── 1. Seed des plans SaaS ────────────────────────────────────────────
        logger.info("Configuring SaaS plans…")
        await ensure_default_saas_plans(session)

        # ── 2. Création du compte Super Admin ─────────────────────────────────
        stmt = select(User).where(User.email == admin_email)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user:
            logger.info("Creating Super Admin: %s", admin_email)

            # Boutique système pour le super admin
            system_store = Store(
                name="AutoCommerce System",
                slug="system-admin",
                is_active=True,
                is_paid=True,
                billing_plan_code="pro_whatsapp",
            )
            session.add(system_store)
            await session.flush()

            new_user = User(
                email=admin_email,
                hashed_password=hash_password(admin_password),
                role="super_admin",
                store_id=system_store.id,
                is_active=True,
            )
            session.add(new_user)
            logger.info("Super Admin created successfully.")
        else:
            logger.info("Super Admin already exists — updating password hash and role.")
            user.hashed_password = hash_password(admin_password)
            user.role = "super_admin"
            user.is_active = True

        await session.commit()

    logger.info("Setup complete.")


if __name__ == "__main__":
    asyncio.run(setup())
