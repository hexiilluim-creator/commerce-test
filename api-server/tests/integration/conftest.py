"""tests/integration/conftest.py — Fixtures partagées pour les tests d'intégration.

Utilise SQLite in-memory (aiosqlite) pour l'isolation complète.
Chaque test reçoit une DB vierge via les fixtures async_client / db_session.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

# ── Forcer SQLite in-memory avant tout import applicatif ──────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
os.environ.setdefault("INSTAGRAM_APP_SECRET", "")
os.environ.setdefault("FACEBOOK_APP_SECRET", "")
os.environ.setdefault("TIKTOK_APP_SECRET", "")
os.environ.setdefault("INSTAGRAM_VERIFY_TOKEN", "test-ig-token")
os.environ.setdefault("FACEBOOK_VERIFY_TOKEN", "test-fb-token")
os.environ.setdefault("TIKTOK_VERIFY_TOKEN", "test-tt-token")
os.environ.setdefault("TIKTOK_ENABLED", "false")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS0zMmNoYXJz")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-000000000000000000000000000000000000000000000000")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-0000")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("SENDGRID_API_KEY", "SG.test.test")
os.environ.setdefault("FROM_EMAIL", "test@example.com")
os.environ.setdefault("SUPER_ADMIN_SECRET", "super-secret-test")
os.environ.setdefault("INTERNAL_HEALTH_TOKEN", "test-health-token-001")
os.environ.setdefault("FLOUCI_APP_TOKEN", "test-flouci-token")
os.environ.setdefault("FLOUCI_APP_SECRET", "test-flouci-secret")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
os.environ.setdefault("AWS_REGION", "eu-west-1")

# ── Imports applicatifs APRÈS la configuration des env vars ───────────────────
# AUDIT FIX : Base.metadata.create_all() ne crée que les tables des modèles
# déjà IMPORTÉS (donc enregistrés sur Base.metadata) au moment de l'appel.
# Ce fichier n'importait explicitement que models.database — les 6 autres
# modules qui étendent ce même Base (b2b_portal, blueprints, loyalty_ia,
# predictive_restocking, visual_builder, security_overlay.models) n'étaient
# enregistrés QUE si un autre import (via main.py, un router, etc.) les avait
# déjà chargés avant cette fixture — dépendant de l'ordre d'exécution des
# tests, donc fragile et non déterministe. Confirmé en production : un test
# a échoué avec "no such table: tenant_subscriptions" (security_overlay.models)
# faute de cet import explicite. Fix : importer tous les modules de modèles
# ici, systématiquement, avant create_all().
import models.b2b_portal  # noqa: E402, F401
import models.blueprints  # noqa: E402, F401
import models.loyalty_ia  # noqa: E402, F401
import models.predictive_restocking  # noqa: E402, F401
import models.visual_builder  # noqa: E402, F401
import security_overlay.models  # noqa: E402, F401

# ── Moteur SQLite in-memory ────────────────────────────────────────────────────
from models.database import (
    Base,  # noqa: E402
    engine,
)

# SQLite ne fournit pas la fonction PostgreSQL set_config utilisée par le
# contexte tenant. Cette compatibilité est limitée aux tests SQLite : elle
# retourne la valeur demandée sans modifier la configuration PostgreSQL.
if engine.dialect.name == "sqlite":
    @event.listens_for(engine.sync_engine, "connect")
    def _register_sqlite_postgres_compat(dbapi_connection, _connection_record):
        dbapi_connection.run_async(
            lambda raw_connection: raw_connection.create_function(
                "set_config", 3, lambda _name, value, _is_local: value
            )
        )


TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
)


@event.listens_for(Session, "after_begin")
def _set_staging_test_rls_context(session, _transaction, connection):
    """Réapplique le rôle de préparation après chaque commit/recheckout PostgreSQL.

    Cette instrumentation est limitée aux sessions marquées par la fixture et ne
    touche pas au chemin applicatif de production.
    """
    if session.info.get("staging_test_super_admin") and connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "SELECT set_config('app.current_user_role', 'super_admin', false)"
        )


@pytest_asyncio.fixture(autouse=True)
async def create_tables():
    """Crée le schéma pour toute la session de test."""
    async with engine.begin() as conn:
        # PostgreSQL: le type VECTOR utilisé par models.database.Product
        # nécessite l'extension pgvector avant Base.metadata.create_all().
        # Sinon les tests d'intégration sur Postgres échouent dès le setup avec
        # UndefinedObjectError: type "vector" does not exist.
        if engine.dialect.name == "postgresql":
            vector_installed = await conn.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            if not vector_installed:
                raise RuntimeError(
                    "pgvector must be provisioned by staging before integration tests"
                )
        await conn.run_sync(Base.metadata.create_all)

    # P1.4-FIX-COMPLEMENT : les tests qui déclenchent la chaîne
    # d'abonnement (ex: pagination SuperAdmin) appellent get_plan_by_code(),
    # qui a besoin d'au moins quelques lignes dans plan_limits. On appelle le
    # service réel (pas une copie de l'INSERT) pour ne jamais diverger de la
    # logique de seeding de production.
    from services.saas_billing import ensure_default_saas_plans

    async with TestingSessionLocal() as seed_session:
        await ensure_default_saas_plans(seed_session)

    yield
    async with engine.begin() as conn:
        # PostgreSQL staging est une base dédiée et provisionnée avant pytest.
        # Ne pas DROP SCHEMA CASCADE ici : cela supprimerait l’extension pgvector
        # installée par l’administrateur et rendrait les scénarios suivants
        # dépendants de l’ordre d’exécution. Le nettoyage de la base staging est
        # effectué par le job de provisioning entre deux campagnes.
        if engine.dialect.name != "postgresql":
            await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Session DB isolée pour chaque test — rollback automatique après.

    Les tests d'intégration métier créent directement des données de préparation
    sans passer par le middleware HTTP. Sur PostgreSQL avec RLS, ils doivent donc
    déclarer explicitement un contexte super_admin de test. Les propriétés RLS
    d'isolation restent couvertes séparément par tests/security/ avec des
    contextes tenant explicites.
    """
    from middleware.tenant import current_user_role

    role_token = current_user_role.set("super_admin") if engine.dialect.name == "postgresql" else None
    try:
        async with TestingSessionLocal() as session:
            if engine.dialect.name == "postgresql":
                session.sync_session.info["staging_test_super_admin"] = True
                await session.execute(
                    text("SELECT set_config('app.current_user_role', 'super_admin', false)")
                )
            yield session
            await session.rollback()
    finally:
        if role_token is not None:
            current_user_role.reset(role_token)


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP async branché sur l'app FastAPI avec la DB de test."""
    from main import app
    from models.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(async_client: AsyncClient, db_session: AsyncSession):
    """Factory de headers auth JWT pour différents rôles."""
    _cache: dict[str, dict[str, str]] = {}

    async def _get(role: str = "admin") -> dict[str, str]:
        if role in _cache:
            return _cache[role]
        suffix = uuid.uuid4().hex[:6]
        email = f"test_{role}_{suffix}@example.com"
        store_name = f"Store {role} {suffix}"
        payload = {
            "email": email,
            "password": "Password123!",
            "store_name": store_name,
        }
        if role == "super_admin":
            # super_admin créé via register puis forcé en DB
            from sqlalchemy import select

            from models.database import User
            resp = await async_client.post("/api/v1/auth/register", json=payload)
            assert resp.status_code in [200, 201], f"register failed: {resp.text}"
            token = resp.json()["access_token"]
            # Forcer le rôle super_admin en DB
            result = await db_session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user:
                user.role = "super_admin"
                await db_session.commit()
            # Ré-émettre un token avec le bon rôle
            from api.v1.auth import create_token
            token = create_token(user.store_id, "super_admin", user_id=user.id)
        else:
            resp = await async_client.post("/api/v1/auth/register", json=payload)
            assert resp.status_code in [200, 201], f"register failed: {resp.text}"
            token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        _cache[role] = headers
        return headers

    return _get
