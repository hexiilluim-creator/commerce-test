"""init_db.py — Initialise la base de données pour le mode demo/dev

PRODUCTION : ce script est pour SQLite dev uniquement.
Pour PostgreSQL production, utiliser :
  1. alembic upgrade head
  (RLS appliqué automatiquement par les migrations 0058→0064)

NOTE INTÉGRATION RLS (audit V28) :
  Le hook GUC tenant DOIT être installé dans models/database.py (non inclus
  dans cet artefact — code propriétaire). Ajouter APRÈS create_async_engine() :

    from services.tenant_db_context import install_tenant_guc_hook
    install_tenant_guc_hook(engine)

  Sans ce hook, current_tenant() retourne NULL dans PostgreSQL → RLS ineffectif.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy.ext.asyncio import create_async_engine

from models.database import Base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./autocommerce_demo.db")


async def init():
    engine = create_async_engine(DATABASE_URL, echo=False)

    # ── Hook GUC tenant (PostgreSQL uniquement) ───────────────────────────────
    # En mode dev SQLite, le hook est ignoré (SQLite n'a pas de GUC).
    # En mode PostgreSQL, installe le bridge ContextVar → app.current_tenant_id.
    if "postgresql" in DATABASE_URL:
        try:
            from services.tenant_db_context import install_tenant_guc_hook
            install_tenant_guc_hook(engine)
            print("[init_db] ✓ Hook RLS tenant installé")
        except Exception as exc:
            print(f"[init_db] ⚠ Hook RLS non installé ({exc}) — vérifier models/database.py")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print(f"[init_db] Tables créées dans: {DATABASE_URL}")


if __name__ == "__main__":
    asyncio.run(init())
