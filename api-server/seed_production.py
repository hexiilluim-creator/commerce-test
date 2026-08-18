import asyncio
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.v1.auth import hash_password
from config import settings as app_settings
from models.database import PaymentProvider, Product, Store, User

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
SEED_LOG_PATH = REPORTS_DIR / "seed.log"


def _require_env(key: str) -> str:
    """Read a required environment variable. Raises RuntimeError if not set."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set. Set it before running the seed script.")
    return value


def _make_async_url(raw: str) -> str:
    import re

    url = raw
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"[?&]connect_timeout=[^&]*", "", url)
    return url.rstrip("?").rstrip("&")


_raw_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://autouser:autopass@localhost/autocommerce",
)
DATABASE_URL = _make_async_url(_raw_url)


def _build_seed_logger() -> structlog.stdlib.BoundLogger:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("seed_production")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(getattr(handler, "baseFilename", None) == str(SEED_LOG_PATH) for handler in logger.handlers):
        handler = logging.FileHandler(SEED_LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.wrap_logger(logger)


async def _ensure_paymentprovider_enum(session: AsyncSession) -> None:
    """Ensure the PostgreSQL enum type `paymentprovider` exists before seeding.

    Production databases occasionally drift when schema migrations were partially
    applied or data was restored from an older dump. The seed must stay resilient
    and create the enum type if it is missing, then backfill missing enum values.
    """
    bind = session.bind
    if bind is None or bind.dialect.name != "postgresql":
        return

    enum_values = [provider.value for provider in PaymentProvider]
    exists_result = await session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'paymentprovider')")
    )
    enum_exists = bool(exists_result.scalar())

    if not enum_exists:
        values_sql = ", ".join(f"'{value}'" for value in enum_values)
        await session.execute(text(f"CREATE TYPE paymentprovider AS ENUM ({values_sql})"))
        return

    for value in enum_values:
        await session.execute(text(f"ALTER TYPE paymentprovider ADD VALUE IF NOT EXISTS '{value}'"))


DEFAULT_STORE_DESCRIPTION = (
    "Boutique de démonstration AutoCommerce prête pour les tests du tunnel "
    "WhatsApp, du catalogue et des paiements. Remplacez ce texte par votre "
    "positionnement réel avant mise en production."
)


def _optional_env(*keys: str) -> str | None:
    """Return the first non-empty, non-placeholder env var among provided keys."""
    placeholders = {
        "your_access_token",
        "your_phone_number_id",
        "change_me",
        "changeme",
    }
    for key in keys:
        value = os.environ.get(key)
        if not value:
            continue
        normalized = value.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in placeholders or lowered.startswith("change_me"):
            continue
        return normalized
    return None


# ---------------------------------------------------------------------------
# V27 : catalogue de démonstration (rapport §1 + §3)
# ---------------------------------------------------------------------------
DEMO_PRODUCTS: list[dict] = [
    {
        "external_code": "DEMO-001",
        "name": "T-shirt Premium Coton Bio",
        "description": "T-shirt 100% coton bio, coupe unisexe, disponible en plusieurs coloris.",
        "price": Decimal("39.900"),
        "stock_qty": 120,
        "category": "vêtement",
        "tags": ["coton", "bio", "unisexe"],
    },
    {
        "external_code": "DEMO-002",
        "name": "Sac à dos urbain 20L",
        "description": "Sac à dos léger et résistant, compartiment ordinateur 15 pouces.",
        "price": Decimal("89.000"),
        "stock_qty": 45,
        "category": "accessoire",
        "tags": ["sac", "urbain", "laptop"],
    },
    {
        "external_code": "DEMO-003",
        "name": "Casque Bluetooth Confort+",
        "description": "Casque sans fil, réduction de bruit active, 30h d'autonomie.",
        "price": Decimal("249.000"),
        "stock_qty": 30,
        "category": "électronique",
        "tags": ["audio", "bluetooth", "casque"],
    },
    {
        "external_code": "DEMO-004",
        "name": "Bouteille isotherme 750 ml",
        "description": "Inox double paroi, conserve chaud 12h et froid 24h.",
        "price": Decimal("49.000"),
        "stock_qty": 200,
        "category": "maison",
        "tags": ["isotherme", "inox", "écolo"],
    },
    {
        "external_code": "DEMO-005",
        "name": "Montre connectée Sport",
        "description": "Cardio, GPS, notifications, autonomie 7 jours, étanche 5 ATM.",
        "price": Decimal("329.000"),
        "stock_qty": 25,
        "category": "électronique",
        "tags": ["montre", "sport", "gps"],
    },
    {
        "external_code": "DEMO-006",
        "name": "Chaussures running légères",
        "description": "Semelle amortissante, poids plume 220 g, idéal route et piste.",
        "price": Decimal("179.000"),
        "stock_qty": 60,
        "category": "vêtement",
        "tags": ["running", "sport", "chaussures"],
    },
]


async def _seed_demo_products(session: AsyncSession, store_id: int, logger: structlog.stdlib.BoundLogger) -> None:
    """Idempotent : crée ou remet à niveau les produits démo pour ce store."""
    demo_codes = [spec["external_code"] for spec in DEMO_PRODUCTS]
    existing_result = await session.execute(
        select(Product).where(Product.store_id == store_id, Product.external_code.in_(demo_codes))
    )
    existing_by_code = {
        product.external_code: product for product in existing_result.scalars().all() if product.external_code
    }

    created = 0
    updated = 0
    for spec in DEMO_PRODUCTS:
        product = existing_by_code.get(spec["external_code"])
        if product is None:
            product = Product(
                store_id=store_id,
                external_code=spec["external_code"],
                name=spec["name"],
                description=spec["description"],
                price=spec["price"],
                stock_qty=spec["stock_qty"],
                category=spec["category"],
                tags=spec["tags"],
                is_active=True,
            )
            session.add(product)
            created += 1
            continue

        changed = False
        for field in ("name", "description", "price", "stock_qty", "category", "tags"):
            if getattr(product, field) != spec[field]:
                setattr(product, field, spec[field])
                changed = True
        if not product.is_active:
            product.is_active = True
            changed = True
        if changed:
            updated += 1

    if created or updated:
        await session.flush()
        logger.info("seed_products", store_id=store_id, created=created, updated=updated)
        print(f"Demo catalog synced: {created} created, {updated} updated.")
    else:
        print("Demo catalog already present — no product change needed.")


async def _already_seeded(session: AsyncSession) -> bool:
    result = await session.execute(text("SELECT EXISTS(SELECT 1 FROM users WHERE role IN ('admin', 'super_admin'))"))
    return bool(result.scalar())


def _seed_demo_content_enabled() -> bool:
    """V28 P0-fix : le seed injectait inconditionnellement un demo-store,
    des numéros/emails/logo de démonstration et un catalogue démo — y compris
    dans le flux de déploiement prod recommandé (README étape 5). Désormais
    ce comportement exige SEED_DEMO_CONTENT=1 explicite. Par défaut (0), la
    seule opération réalisée est la création des comptes admin/superadmin
    (obligatoire pour pouvoir se connecter), sur un store dont l'identité
    doit être fournie via STORE_SLUG/STORE_NAME."""
    return os.environ.get("SEED_DEMO_CONTENT", "0").strip().lower() in ("1", "true", "yes")


async def seed() -> int:
    logger = _build_seed_logger()
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    demo_content = _seed_demo_content_enabled()

    try:
        async with async_session() as session:
            # Bootstrap RLS : le seed est un processus d'administration explicite.
            # Les migrations activent FORCE ROW LEVEL SECURITY et toutes les écritures
            # doivent donc disposer d'un contexte autorisé avant le premier SELECT/flush.
            # Ce contexte reste limité à cette session de seed et n'est jamais exposé
            # par les routes HTTP.
            await session.execute(
                text("SELECT set_config('app.current_user_role', 'super_admin', false)")
            )
            await _ensure_paymentprovider_enum(session)

            # V26 : même si les admins sont déjà présents, on continue pour
            # backfill les champs de configuration manquants et le catalogue
            # démo (opérations idempotentes).
            already_seeded = await _already_seeded(session)
            if already_seeded:
                print("Admin users already present — running idempotent backfill only.")

            store_slug = os.environ.get("STORE_SLUG") or ("demo-store" if demo_content else None)
            if not store_slug:
                raise RuntimeError(
                    "STORE_SLUG doit être défini (ou SEED_DEMO_CONTENT=1 pour utiliser "
                    "'demo-store' en environnement de démo/dev)."
                )

            result = await session.execute(select(Store).where(Store.slug == store_slug))
            store = result.scalar_one_or_none()

            # V27 FIX (rapport §1 + audit) : backfill honnête et complet des
            # champs publics + possibilité de brancher un vrai canal WhatsApp si
            # les variables Meta sont réellement fournies dans l'environnement.
            #
            # V28 P0-fix : les valeurs "+21671000000" / logo demo-store / prompt
            # générique n'étaient utilisées comme fallback que si SEED_DEMO_CONTENT
            # est explicitement activé. Sinon on exige les vraies valeurs via env.
            def _store_field(demo_env_key: str, demo_default: str) -> str:
                value = os.environ.get(demo_env_key, "")
                if value:
                    return value
                if demo_content:
                    return demo_default
                raise RuntimeError(
                    f"{demo_env_key} doit être défini (ou SEED_DEMO_CONTENT=1 pour "
                    "utiliser des valeurs de démonstration)."
                )

            demo_whatsapp = _store_field("DEMO_WHATSAPP_PHONE", "+21671000000")
            demo_owner_phone = _store_field("DEMO_OWNER_PHONE", "+21620000000")
            demo_support_email = _store_field("DEMO_SUPPORT_EMAIL", "contact@autocommerce.tn")
            demo_logo_url = _store_field(
                "DEMO_LOGO_URL", "https://cdn.autocommerce.tn/branding/demo-store-logo.png",
            )
            demo_ai_prompt = _store_field(
                "STORE_AI_PROMPT",
                "Tu es l'assistant commercial d'AutoCommerce. Réponds aux clients "
                "en français, propose les produits actifs et guide vers la commande WhatsApp.",
            )
            demo_order_confirmation = _store_field(
                "STORE_ORDER_CONFIRMATION_MSG",
                "Merci pour votre commande ! Nous la préparons et revenons vers vous très vite.",
            )
            demo_phone_number_id = _optional_env("DEMO_WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_PHONE_NUMBER_ID")
            demo_access_token = _optional_env("DEMO_WHATSAPP_ACCESS_TOKEN", "WHATSAPP_ACCESS_TOKEN")

            if not store:
                store = Store(
                    name="Demo Store",
                    slug="demo-store",
                    country="TN",
                    onboarding_completed=True,
                    billing_plan_code="enterprise",
                    billing_status="active",
                    whatsapp_phone=demo_whatsapp,
                    owner_phone=demo_owner_phone,
                    support_email=demo_support_email,
                    logo_url=demo_logo_url,
                    category="retail",
                    language="fr",
                    timezone="Africa/Tunis",
                    ai_agent_prompt=demo_ai_prompt,
                    order_confirmation_msg=demo_order_confirmation,
                )
                if demo_access_token and demo_phone_number_id:
                    store.whatsapp_access_token_enc = app_settings.encrypt(demo_access_token)
                    store.whatsapp_phone_number_id = demo_phone_number_id
                session.add(store)
                await session.flush()
                print("Store created with full public configuration.")
            else:
                # V27 : compléter TOUS les champs réellement utilisés par l'UI de
                # complétude et raccorder WhatsApp si de vraies creds existent.
                store.whatsapp_phone = store.whatsapp_phone or demo_whatsapp
                store.owner_phone = store.owner_phone or demo_owner_phone
                store.support_email = store.support_email or demo_support_email
                store.logo_url = store.logo_url or demo_logo_url

                store.category = store.category or "retail"
                store.language = store.language or "fr"
                store.timezone = store.timezone or "Africa/Tunis"
                store.ai_agent_prompt = store.ai_agent_prompt or demo_ai_prompt
                store.order_confirmation_msg = store.order_confirmation_msg or demo_order_confirmation
                if not store.whatsapp_phone_number_id and demo_phone_number_id:
                    store.whatsapp_phone_number_id = demo_phone_number_id
                if not store.whatsapp_access_token_enc and demo_access_token:
                    store.whatsapp_access_token_enc = app_settings.encrypt(demo_access_token)
                print("Store already exists — missing public and channel fields backfilled.")

            # FIX V25 Enterprise: le store de démonstration doit être semé avec
            # un plan actif compatible avec les modules visibles dans l'UI.
            store.billing_plan_code = store.billing_plan_code or "enterprise"
            store.billing_status = store.billing_status or "active"

            # Bloc admin/superadmin : on ne recrée que si absent.
            # Les mots de passe sont exigés uniquement en cas de création.
            result = await session.execute(select(User).where(User.email == "admin@autocommerce.tn"))
            user = result.scalar_one_or_none()
            if not user:
                user = User(
                    email="admin@autocommerce.tn",
                    hashed_password=hash_password(_require_env("ADMIN_INITIAL_PASSWORD")),
                    role="admin",
                    store_id=store.id,
                    is_active=True,
                )
                session.add(user)
                logger.info(
                    "seed_insert",
                    email=user.email,
                    role=user.role,
                )
                print("Admin user created (admin@autocommerce.tn). Password from ADMIN_INITIAL_PASSWORD env var.")
            else:
                print("Admin user already exists.")

            result = await session.execute(select(User).where(User.email == "superadmin@autocommerce.tn"))
            super_user = result.scalar_one_or_none()
            if not super_user:
                super_user = User(
                    email="superadmin@autocommerce.tn",
                    hashed_password=hash_password(_require_env("SUPERADMIN_INITIAL_PASSWORD")),
                    role="super_admin",
                    store_id=store.id,
                    is_active=True,
                )
                session.add(super_user)
                logger.info(
                    "seed_insert",
                    email=super_user.email,
                    role=super_user.role,
                )
                print("Super Admin user created. Password from SUPERADMIN_INITIAL_PASSWORD env var.")
            else:
                print("Super Admin user already exists.")

            # V26 FIX (rapport §3): seed d'un catalogue produits minimal actif
            # pour que le tableau de bord et les recommandations IA ne renvoient
            # plus zéro. Idempotent : n'ajoute que les produits manquants.
            # V28 P0-fix : ce catalogue est fait de données de démonstration —
            # désormais réservé à SEED_DEMO_CONTENT=1 pour ne plus polluer un
            # store de production réel avec des produits factices.
            if demo_content:
                await _seed_demo_products(session, store.id, logger)
            else:
                print("SEED_DEMO_CONTENT non activé — catalogue démo non injecté.")

            await session.commit()
        print("Seeding completed successfully.")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(seed()))
