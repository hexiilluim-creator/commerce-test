"""create_admin.py — utilitaire de développement pour créer un admin local.

V28 P1-fix : ce script avait un mot de passe codé en dur ("admin_robust_2026")
et un email fixe, sans passer par la validation de preflight_secrets.py ni par
ENV_INITIAL_PASSWORD. Il n'était appelé par aucun script/Makefile/Dockerfile,
mais restait exécutable manuellement contre une base de prod avec un mot de
passe trivial connu de quiconque a lu ce fichier.

Corrections :
  - Refuse de s'exécuter si ENV n'est pas development/test (sauf override
    explicite ALLOW_CREATE_ADMIN_IN_PROD=1).
  - Le mot de passe doit venir de ADMIN_INITIAL_PASSWORD (obligatoire, >= 12
    caractères), plus de valeur par défaut codée en dur.
  - L'email est configurable via ADMIN_INITIAL_EMAIL (défaut dev uniquement).
"""
import asyncio
import os
import sys

# Add current directory to sys.path to allow absolute imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api.v1.auth import hash_password
from models import AsyncSessionLocal, Store, User


def _guard_environment() -> None:
    env = os.environ.get("ENV", "development").strip().lower()
    override = os.environ.get("ALLOW_CREATE_ADMIN_IN_PROD", "0").strip().lower() in ("1", "true", "yes")
    if env not in ("development", "dev", "test") and not override:
        print(
            f"create_admin.py: refuse de s'executer (ENV={env!r}). Ce script est reserve au "
            "developpement local ; utilisez seed_production.py avec ADMIN_INITIAL_PASSWORD "
            "pour la production, ou definissez ALLOW_CREATE_ADMIN_IN_PROD=1 si c'est volontaire."
            ,
            file=sys.stderr,
        )
        sys.exit(1)


def _require_password() -> str:
    password = os.environ.get("ADMIN_INITIAL_PASSWORD", "")
    if not password or len(password) < 12:
        print(
            "create_admin.py: ADMIN_INITIAL_PASSWORD est requis (>= 12 caracteres) — "
            "plus de mot de passe par defaut code en dur.",
            file=sys.stderr,
        )
        sys.exit(1)
    return password


async def create_admin():
    _guard_environment()
    password = _require_password()
    email = os.environ.get("ADMIN_INITIAL_EMAIL", "admin@example.com")

    async with AsyncSessionLocal() as session:
        # Check if store exists
        from sqlalchemy import select
        result = await session.execute(select(Store).where(Store.id == 1))
        store = result.scalar_one_or_none()

        if not store:
            store = Store(id=1, name="Default Store", slug="default-store")
            session.add(store)
            await session.flush()

        admin = User(
            email=email,
            hashed_password=hash_password(password),
            role="admin",
            is_active=True,
            store_id=store.id
        )
        session.add(admin)
        await session.commit()
        print(f"Admin created successfully ({email})")

if __name__ == "__main__":
    asyncio.run(create_admin())
