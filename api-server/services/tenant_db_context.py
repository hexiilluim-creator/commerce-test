"""
services/tenant_db_context.py — Bridge Python ContextVar → PostgreSQL GUC
==========================================================================
PROBLÈME FONDAMENTAL :
  - Le middleware tenant.py stocke le tenant courant dans un ContextVar Python
    (current_tenant_id: ContextVar[int | None]).
  - Les migrations Alembic (0058→0064) créent les policies RLS qui utilisent
    current_setting('app.current_tenant_id') depuis la session PostgreSQL.
  - Ces deux systèmes sont INDÉPENDANTS : sans ce bridge, RLS retourne NULL
    pour tous les contextes tenant → les policies bloquent toutes les requêtes
    (FORCE RLS + USING (store_id = NULL) → zéro résultat).

SOLUTION :
  Ce module fournit un bridge qui injecte les GUC tenant sur la connexion
  PostgreSQL pendant la requête et les réinitialise systématiquement avant sa
  restitution au pool. Les routes peuvent donc committer plusieurs fois sans
  perdre le contexte RLS, sans laisser un tenant fuiter vers la requête suivante.

INTÉGRATION (dans models/database.py) :
  Remplacer AsyncSessionLocal par tenant_session() dans toutes les routes
  qui nécessitent la protection RLS, OU utiliser l'event hook ci-dessous
  pour patcher automatiquement toutes les sessions.

  Option A (recommandée — automatique) :
    Dans models/database.py, après la définition du engine, ajouter :
      from services.tenant_db_context import install_tenant_guc_hook
      install_tenant_guc_hook(engine)

  Option B (explicite par route) :
    Remplacer AsyncSessionLocal() par tenant_session() dans les dépendances FastAPI.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import TYPE_CHECKING

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Référence aux ContextVars définis dans middleware/tenant.py
# On les importe ici pour lire la valeur courante lors de chaque connexion.
_current_tenant_id: ContextVar[int | None] | None = None
_current_user_role: ContextVar[str | None] | None = None


def _load_contextvars() -> None:
    """Charge les ContextVars depuis middleware/tenant.py (import lazy pour éviter les cycles)."""
    global _current_tenant_id, _current_user_role
    if _current_tenant_id is None:
        try:
            from middleware.tenant import current_tenant_id, current_user_role
            _current_tenant_id = current_tenant_id
            _current_user_role = current_user_role
        except ImportError:
            logger.warning("tenant_db_context: impossible de charger middleware.tenant — GUC non injectés")


def _get_tenant_id() -> int | None:
    _load_contextvars()
    if _current_tenant_id is None:
        return None
    return _current_tenant_id.get()


def _get_user_role() -> str | None:
    _load_contextvars()
    if _current_user_role is None:
        return None
    return _current_user_role.get()


# =============================================================================
# Option A : Event hook automatique (à installer une fois dans models/database.py)
# =============================================================================

def install_tenant_guc_hook(engine: AsyncEngine) -> None:
    """
    Installe un event hook SQLAlchemy qui injecte les GUC tenant dans chaque
    nouvelle connexion PostgreSQL.

    À appeler UNE SEULE FOIS après la création du moteur SQLAlchemy :
        from services.tenant_db_context import install_tenant_guc_hook
        install_tenant_guc_hook(engine)

    L'event 'connect' est synchrone et s'exécute au niveau DBAPI (asyncpg/psycopg2).
    Pour asyncpg, utiliser l'event 'checkout' qui est async-compatible.
    """
    try:
        from sqlalchemy.pool import AsyncAdaptedQueuePool

        @event.listens_for(engine.sync_engine, "checkout")
        def _on_checkout(dbapi_conn, connection_record, connection_proxy):
            """
            Injecte les GUC avant chaque checkout de connexion.
            NOTE: 'checkout' est synchrone même pour asyncpg dans SQLAlchemy 2.x.
            Les valeurs sont lues depuis les ContextVars asyncio courants.
            """
            tenant_id = _get_tenant_id()
            role = _get_user_role() or "user"

            cursor = dbapi_conn.cursor()
            try:
                # SET est volontairement session-scoped ici : checkout peut
                # précéder plusieurs transactions d’une même requête. On remet
                # toujours les GUC à vide quand aucun tenant n’est présent afin
                # d’empêcher toute fuite inter-tenant via le pool.
                safe_tenant = str(tenant_id) if tenant_id is not None else ""
                safe_role = str(role).replace("'", "''") if tenant_id is not None else ""
                cursor.execute(f"SET app.current_tenant_id = '{safe_tenant}'")
                cursor.execute(f"SET app.current_user_role = '{safe_role}'")
            finally:
                cursor.close()

        logger.info("tenant_db_context: GUC hook installé sur le moteur SQLAlchemy")

    except Exception as exc:
        logger.error("tenant_db_context: échec installation GUC hook: %s", exc)
        raise RuntimeError(
            "Impossible d'installer le hook RLS tenant. "
            "Le multi-tenant ne sera pas protégé par RLS. Vérifiez la configuration SQLAlchemy."
        ) from exc


# =============================================================================
# Option B : Session factory explicite (alternative à AsyncSessionLocal)
# =============================================================================

async def tenant_session(session_factory: async_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    """
    Session factory async qui injecte les GUC tenant via SET LOCAL au début
    de chaque transaction.

    Usage dans les dépendances FastAPI :
        async def get_db():
            async for session in tenant_session(AsyncSessionLocal):
                yield session

    La différence avec AsyncSessionLocal() directement :
        → Cette fonction exécute set_config(..., false) au début de chaque
          session et réinitialise les GUC dans le bloc finally. La portée est
          donc la session louée au pool, pas une transaction qui pourrait être
          fermée par un commit métier pendant la requête.
    """
    tenant_id = _get_tenant_id()
    role = _get_user_role() or "user"

    async with session_factory() as session:
        try:
            if tenant_id is not None:
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": str(tenant_id)},
                )
                await session.execute(
                    text("SELECT set_config('app.current_user_role', :role, false)"),
                    {"role": role},
                )
            yield session
        finally:
            try:
                await session.rollback()
                if tenant_id is not None:
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', '', false)"),
                    )
                    await session.execute(
                        text("SELECT set_config('app.current_user_role', '', false)"),
                    )
            except Exception:
                logger.debug("tenant_db_context: failed to reset session GUCs", exc_info=True)


# =============================================================================
# Utilitaire : vérification que le GUC est bien positionné (tests)
# =============================================================================

async def assert_tenant_guc_set(session: AsyncSession) -> str | None:
    """
    Vérifie que app.current_tenant_id est positionné dans la session PG courante.
    Retourne la valeur ou None. Utiliser en tests pour valider l'intégration.

    Exemple :
        async with AsyncSessionLocal() as db:
            tenant_id = await assert_tenant_guc_set(db)
            assert tenant_id == str(expected_tenant_id)
    """
    result = await session.execute(
        text("SELECT current_setting('app.current_tenant_id', true)")
    )
    value = result.scalar_one_or_none()
    return value if value else None


__all__ = [
    "install_tenant_guc_hook",
    "tenant_session",
    "assert_tenant_guc_set",
]
