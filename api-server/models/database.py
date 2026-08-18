import logging
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from services.tenant_db_context import install_tenant_guc_hook

try:
    from pgvector.sqlalchemy import Vector as _PGVector
except ImportError:  # graceful degradation if pgvector not installed (tests/CI)
    _PGVector = None
import enum
from datetime import date as date_type
from datetime import datetime
from typing import Optional

from config import settings

# ─── Engine ────────────────────────────────────────────────────────────────────
# FIX3: Tuned for 1000+ tenants.
# With PgBouncer (transaction mode): keep pool_size LOW per process (5-10).
# Without PgBouncer: pool_size = (PG_MAX_CONN - 5) / (workers × pods).
# pool_pre_ping prevents stale connection errors on idle tenants.
# pool_recycle avoids connections held open > 30 min (cloud DB idle timeout).
engine_kwargs = {
    "echo": settings.DEBUG,
}
if "sqlite" not in settings.DATABASE_URL:
    engine_kwargs.update({
        "pool_size": int(getattr(settings, "DB_POOL_SIZE", 20)),  # Optimized for SaaS
        "max_overflow": int(getattr(settings, "DB_MAX_OVERFLOW", 10)),
        "pool_timeout": 10,      # fail fast — never queue > 10s
        "pool_recycle": 1800,    # recycle every 30 min (avoids idle drops)
        "pool_pre_ping": True,   # verify connection alive before checkout
    })

def _make_async_url(raw: str) -> str:
    """Convert sync postgresql:// URL to asyncpg scheme and strip unsupported params."""
    import re
    url = raw
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    # asyncpg doesn't accept sslmode/connect_timeout as query params
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"[?&]connect_timeout=[^&]*", "", url)
    url = url.rstrip("?").rstrip("&")
    return url

if settings.ENV == "test" and "sqlite" in settings.DATABASE_URL:
    from sqlalchemy.pool import StaticPool
    engine = create_async_engine(
        _make_async_url(settings.DATABASE_URL),
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        **engine_kwargs
    )
elif settings.ENV == "test":
    # Les TestClient peuvent créer plusieurs boucles asyncio successives. Une
    # connexion asyncpg mise en pool entre ces boucles produit un Future attaché
    # à une autre boucle. NullPool est limité au mode test et rend le staging
    # reproductible sans modifier le pool de production.
    from sqlalchemy.pool import NullPool
    test_engine_kwargs = {
        key: value
        for key, value in engine_kwargs.items()
        if key not in {"pool_size", "max_overflow", "pool_timeout", "pool_recycle", "pool_pre_ping"}
    }
    engine = create_async_engine(
        _make_async_url(settings.DATABASE_URL),
        poolclass=NullPool,
        **test_engine_kwargs
    )
else:
    engine = create_async_engine(
        _make_async_url(settings.DATABASE_URL),
        **engine_kwargs
    )

# V28.2 FIX: Install the RLS bridge hook to sync Python ContextVar with Postgres GUC
logger = logging.getLogger(__name__)
# P1.5-FIX : n'installer le hook que sur PostgreSQL — RLS/GUC est une notion
# Postgres, et le hook exécute `SET app.current_tenant_id = ...` à chaque
# checkout de connexion, une syntaxe que SQLite ne supporte pas (utilisé en
# tests/dev via _make_async_url ci-dessus). Vérifié sur le dialecte SQLAlchemy
# résolu de l'engine réel, pas sur un test de sous-chaîne de l'URL brute —
# plus robuste (indépendant du contenu de la chaîne de connexion).
if engine.dialect.name == "postgresql":
    install_tenant_guc_hook(engine)
else:
    logger.warning(
        "tenant_db_context: hook RLS non installé (dialecte=%s, attendu postgresql) — "
        "normal en dev/test SQLite, ANORMAL en production.",
        engine.dialect.name,
    )

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


from collections.abc import AsyncGenerator


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # C6 FIX: return type was AsyncSession but this is a generator (yields, not returns)
    # Correct type is AsyncGenerator[AsyncSession, None] for FastAPI Depends injection
    from sqlalchemy import text

    from middleware.tenant import current_tenant_id, current_user_role

    async with AsyncSessionLocal() as session:
        tenant_id = current_tenant_id.get()
        user_role = current_user_role.get()
        apply_rls_context = (
            tenant_id is not None
            and "sqlite" not in settings.DATABASE_URL
        )

        if apply_rls_context:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"),
                {"tenant_id": str(int(tenant_id))},
            )
            await session.execute(
                text("SELECT set_config('app.current_user_role', :user_role, false)"),
                {"user_role": str(user_role or "viewer")},
            )

        try:
            yield session
        finally:
            if apply_rls_context:
                try:
                    await session.rollback()
                    await session.execute(text("SELECT set_config('app.current_tenant_id', '', false)"))
                    await session.execute(text("SELECT set_config('app.current_user_role', '', false)"))
                    await session.rollback()
                except Exception:
                    logger.debug("database.get_db: failed to reset RLS context", exc_info=True)


class Base(DeclarativeBase):
    pass


# ─── Enums ─────────────────────────────────────────────────────────────────────
class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"    # P1 FIX: client returned goods
    REFUNDED = "refunded"    # P1 FIX: refund processed


class PaymentProvider(enum.StrEnum):
    FLOUCI = "flouci"
    CLIX = "clix"
    TNPAY = "tnpay"
    CASH = "cash"
    STRIPE = "stripe"
    CMI = "cmi"
    ALIAPAY = "aliapay"
    NEXUS = "nexus"


class PaymentLinkStatus(enum.StrEnum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"
    FAILED = "failed"


class MessageType(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    INTERACTIVE = "interactive"


# ─── Models ────────────────────────────────────────────────────────────────────
class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(20))
    # Numéro WhatsApp du marchand — messages entrants de ce numéro -> mode admin
    owner_phone: Mapped[str | None] = mapped_column(String(20), index=True)
    # ── Auto Parts / Stock Sources ──────────────────────────────────────────
    stock_source_type: Mapped[str | None] = mapped_column(String(30))
    stock_source_config_enc: Mapped[str | None] = mapped_column(Text)
    # OEM APIs
    tecdoc_api_key_enc: Mapped[str | None] = mapped_column(Text)
    tecdoc_provider_id: Mapped[str | None] = mapped_column(String(64))
    autoiso_api_key_enc: Mapped[str | None] = mapped_column(Text)
    nhtsa_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_parts_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_config: Mapped[dict | None] = mapped_column(JSON)          # encrypted keys
    stock_api_url: Mapped[str | None] = mapped_column(String(500))
    stock_api_key_enc: Mapped[str | None] = mapped_column(Text)        # encrypted
    ai_agent_prompt: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(5), default="fr")
    timezone: Mapped[str] = mapped_column(String(50), default="Africa/Tunis")
    logo_url: Mapped[str | None] = mapped_column(String(1000))
    banner_url: Mapped[str | None] = mapped_column(String(1000))
    
    # Liens Sociaux Publics (Direct Contact)
    messenger_page_id: Mapped[str | None] = mapped_column(String(100))
    instagram_handle: Mapped[str | None] = mapped_column(String(100))
    tiktok_handle: Mapped[str | None] = mapped_column(String(100))
    support_email: Mapped[str | None] = mapped_column(String(255))
    order_confirmation_msg: Mapped[str | None] = mapped_column(Text)
    post_payment_msg: Mapped[str | None] = mapped_column(Text)
    conversation_timeout_min: Mapped[int] = mapped_column(Integer, default=30)
    # E23: per-store WhatsApp credentials (encrypted) — overrides global settings
    whatsapp_access_token_enc: Mapped[str | None] = mapped_column(Text)
    whatsapp_phone_number_id: Mapped[str | None] = mapped_column(String(64))

    # ── Social media BYOK (tokens chiffrés Fernet) ──────────────────────────
    # Instagram
    instagram_token_enc: Mapped[str | None] = mapped_column(Text)
    instagram_account_id: Mapped[str | None] = mapped_column(String(64))
    instagram_username: Mapped[str | None] = mapped_column(String(100))
    # Facebook
    facebook_token_enc: Mapped[str | None] = mapped_column(Text)
    facebook_page_id: Mapped[str | None] = mapped_column(String(64))
    facebook_page_name: Mapped[str | None] = mapped_column(String(100))
    # TikTok
    tiktok_token_enc: Mapped[str | None] = mapped_column(Text)
    tiktok_open_id: Mapped[str | None] = mapped_column(String(64))
    tiktok_username: Mapped[str | None] = mapped_column(String(100))

    # ── OpenAI BYOK (clé chiffrée Fernet AES-256) ───────────────────────────
    # Clé OpenAI propre au tenant (jamais stockée ni renvoyée en clair).

    category: Mapped[str | None]          = mapped_column(String(64))
    # ── Champs Vitrine Publique ──
    opening_hours: Mapped[dict | None]    = mapped_column(JSON) # {"mon": "09:00-18:00", ...}
    services: Mapped[list | None]         = mapped_column(JSON) # ["Livraison", "Paiement à la livraison"]
    latitude: Mapped[float | None]        = mapped_column(Float)
    longitude: Mapped[float | None]       = mapped_column(Float)
    # Liens Sociaux Publics (distincts des tokens API)
    social_links: Mapped[dict | None]     = mapped_column(JSON) # {"youtube": "...", "messenger": "...", ...}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_type: Mapped[str | None] = mapped_column(String(20)) # legacy field
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billing_plan_code: Mapped[str | None] = mapped_column(String(32), index=True)
    billing_status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", index=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    # ── Multi-pays / multi-devises ───────────────────────────────────────────
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, comment="ISO 3166-1 alpha-2: TN, AE, MA, DZ, ...")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TND", server_default="TND", comment="ISO 4217 settlement currency for this store")
    vat_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_prefix: Mapped[str] = mapped_column(String(10), default="INV", server_default="INV")
    credit_note_prefix: Mapped[str] = mapped_column(String(10), default="AV", server_default="AV")
    default_tax_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tax_inclusive_pricing: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # ── BYOK OpenAI — SUPPRIMÉ (v14.1 / migration 0029) ──────────────────────────
    # Les colonnes openai_api_key_enc, openai_api_key_last4, openai_byok_enabled,
    # openai_model_override, openai_key_updated_at ont été retirées de la table
    # `stores` par la migration 0029_remove_byok_openai_columns.
    # Elles ne doivent PLUS être déclarées ici — sinon SQLAlchemy génère un
    # SELECT incluant ces colonnes et toute requête sur Store échoue avec
    # "column stores.openai_api_key_enc does not exist" après application
    # de la migration 0029.

    # ── Extra config JSON (catch-all for integrations not yet modeled) ────────────
    extra_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", comment="Provider de paiement configuré")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    products: Mapped[list["Product"]] = relationship("Product", back_populates="store")
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="store")
    users: Mapped[list["User"]] = relationship("User", back_populates="store")

    # FIX P2: Relations déplacées depuis monkey-patches en fin de fichier -> déclaration directe.
    # SQLAlchemy résout les forward-references via les strings — aucun changement de comportement.
    business_config: Mapped[Optional["BusinessConfig"]] = relationship(
        "BusinessConfig", back_populates="store", uselist=False
    )
    social_post_config: Mapped[Optional["SocialPostConfig"]] = relationship(
        "SocialPostConfig", back_populates="store", uselist=False
    )
    social_posts: Mapped[list["SocialPost"]] = relationship(
        "SocialPost",
        back_populates="store",
        # R8-FIX: string "Model.col.desc()" is deprecated in SQLAlchemy 2.x.
        # Use order_by=text(...) or omit here and sort at query time.
        order_by="desc(SocialPost.created_at)",
    )
    payment_links: Mapped[list["PaymentLink"]] = relationship(
        "PaymentLink",
        back_populates="store",
        # RC2-FIX: string "Model.col.desc()" is deprecated in SQLAlchemy 2.x (same fix as social_posts R8).
        order_by="desc(PaymentLink.created_at)",
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="admin") # 'super_admin' or 'admin'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    store: Mapped["Store"] = relationship("Store", back_populates="users")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    external_code: Mapped[str | None] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    stock_qty: Mapped[int] = mapped_column(Integer, default=0)
    stock_reserved: Mapped[int] = mapped_column(Integer, default=0)  # E19: reserved by confirmed orders
    category: Mapped[str | None] = mapped_column(String(100))
    tax_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    tags: Mapped[list | None] = mapped_column(JSON)                    # ["nike","t-shirt","black"]
    image_url: Mapped[str | None] = mapped_column(String(1000))  # Legacy: single image URL (backward compatibility)
    images: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)  # V19.2: Multiple images per product (max 3-5 per plan)
    image_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # V19.2: Quick quota check without deserializing JSON
    # FIX M3: migrated from JSON -> pgvector Vector(1536) for native ANN search.
    # Enables HNSW index (see __table_args__) for sub-millisecond similarity search
    # at > 10k products per tenant. Fallback to JSON column on non-pgvector DBs.
    embedding: Mapped[list[float] | None] = mapped_column(
        _PGVector(1536) if _PGVector is not None else JSON,  # B3-FIX: list[float] is accurate for a 1536-dim embedding
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    store: Mapped["Store"] = relationship("Store", back_populates="products")
    variants: Mapped[list["ProductVariant"]] = relationship(
        "ProductVariant",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    # FIX M3: HNSW index for pgvector ANN (approximate nearest-neighbour) search.
    # Cosine distance — standard for text embeddings (OpenAI text-embedding-3-small).
    # ef_construction=128 balances build speed vs recall. m=16 = 16 neighbours per layer.
    # Without this index, embedding search is O(n) table scan — unusable at > 5k products.
    # R5-FIX: Avoid SAWarning from empty __table_args__ when pgvector unavailable.
    # The HNSW index is only meaningful when pgvector is installed.
    # Alembic migration 0025 handles this at the DB level (idempotent).
    __table_args__ = (
        Index(
            "ix_products_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": "16", "ef_construction": "128"},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    ) if _PGVector is not None else ()


class ProductVariant(Base):
    """Simple product variants (size/color/SKU) used by Plan E restocking.

    Kept intentionally lightweight so it can be adopted incrementally without
    breaking existing single-SKU products.
    """
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    option_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    price_override: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    stock_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stock_reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product: Mapped["Product"] = relationship("Product", back_populates="variants")
    store: Mapped["Store"] = relationship("Store")

    __table_args__ = (
        UniqueConstraint("store_id", "sku", name="uq_product_variants_store_sku"),
        Index("ix_product_variants_store_product", "store_id", "product_id"),
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    whatsapp_phone: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    conversation_state: Mapped[dict | None] = mapped_column(JSON)
    last_emotion: Mapped[str | None] = mapped_column(String(50))
    preferences: Mapped[dict | None] = mapped_column(JSON)
    language: Mapped[str] = mapped_column(String(5), default="fr")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opted_out: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        comment="True si le client a demandé à ne plus recevoir de broadcasts",
    )
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── BLOC 10 : canal omnicanal ─────────────────────────────────────────────
    # Canal d'origine du client : whatsapp | instagram | facebook | tiktok
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", server_default="whatsapp")
    # Identifiant social (PSID Instagram/Facebook ou Open ID TikTok) — null pour WhatsApp
    social_sender_id: Mapped[str | None] = mapped_column(String(128))

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="customer")
    # identities: Mapped[list["CustomerIdentity"]] = relationship("CustomerIdentity", back_populates="customer")
    # endpoints: Mapped[list["ContactEndpoint"]] = relationship("ContactEndpoint", back_populates="customer")

    __table_args__ = (
        # E22: unique constraint prevents race condition creating duplicate customers
        # for the same phone number in the same store
        UniqueConstraint("store_id", "whatsapp_phone", name="uq_customers_store_phone"),
        UniqueConstraint("store_id", "channel", "social_sender_id", name="uq_customers_store_channel_sender"),
        # BLOC 10: lookup rapide par canal + sender_id social
        Index("ix_customers_store_channel_sender", "store_id", "channel", "social_sender_id"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus, values_callable=lambda x: [e.value for e in x]), default=OrderStatus.PENDING)
    items: Mapped[list] = mapped_column(JSON)                              # [{product_id, name, qty, unit_price}]
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    subtotal_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tax_breakdown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    promotion_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    promotion_breakdown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    payment_provider: Mapped[PaymentProvider | None] = mapped_column(SAEnum(PaymentProvider, values_callable=lambda x: [e.value for e in x]))
    # Provenance de la commande : storefront public, WhatsApp, Instagram, etc.
    channel: Mapped[str] = mapped_column(String(32), default="direct", server_default="direct", index=True)
    payment_transaction_id: Mapped[str | None] = mapped_column(String(255))
    payment_event_id: Mapped[str | None] = mapped_column(String(255), unique=True)  # idempotency
    delivery_address: Mapped[str | None] = mapped_column(Text)
    delivery_name: Mapped[str | None] = mapped_column(String(255))   # P0-7: customer name collected by agent
    notes: Mapped[str | None] = mapped_column(Text)
    # AUDIT FIX : index ajouté sur created_at — tri/filtre des commandes par
    # date est une requête fréquente en usage SaaS (dashboard, exports,
    # rapports périodiques). Voir migration 0054_add_order_created_at_index.py
    # pour la création réelle de l'index en base (déclarer index=True ici
    # seul ne suffit pas sur une base déjà déployée sans migration).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    store: Mapped["Store"] = relationship("Store", back_populates="orders")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders")


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    wa_message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    from_phone: Mapped[str] = mapped_column(String(20))
    message_type: Mapped[MessageType] = mapped_column(SAEnum(MessageType, values_callable=lambda x: [e.value for e in x]))
    content: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[str | None] = mapped_column(String(255))
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)             # vision result
    ai_response: Mapped[str | None] = mapped_column(Text)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Social channels support — direction field for outbound manual replies
    direction: Mapped[str] = mapped_column(String(16), default="inbound", server_default="inbound")
    # Manual reply flag — True when merchant typed the reply (not IA)
    # Displayed differently in Conversations UI (amber bubble vs indigo)
    is_manual_reply: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StorePhoneMapping(Base):
    """Maps a WhatsApp phone_number_id -> store_id for real multi-tenant routing."""
    __tablename__ = "store_phone_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_number_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    display_phone: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    store: Mapped["Store"] = relationship("Store")


# AUDIT FIX : services/store_resolver.py référence cette table depuis sa
# création (docstring : "3. DB PostgreSQL via StoreSocialMapping — vérité
# absolue") pour résoudre store_id depuis un compte Instagram/Facebook/
# TikTok/Messenger (WhatsApp a sa propre table, StorePhoneMapping
# ci-dessus). Le modèle n'avait jamais été créé -> ImportError masqué
# jusqu'ici par un bug de mock qui empêchait ce chemin de code de
# s'exécuter en test.
class StoreSocialMapping(Base):
    """Maps a social account_id (Instagram/Facebook/TikTok/Messenger) -> store_id."""
    __tablename__ = "store_social_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)
    account_id: Mapped[str] = mapped_column(String(128), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    store: Mapped["Store"] = relationship("Store")

    __table_args__ = (
        UniqueConstraint("channel", "account_id", name="uq_store_social_mappings_channel_account"),
    )


# ─── P1: Conversation state FSM log ──────────────────────────────────────────
class ConversationLog(Base):
    __tablename__ = "conversation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50))
    trigger: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict | None] = mapped_column(JSON)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    # BLOC 10 : canal du message déclencheur
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp", server_default="whatsapp")
    # C4-FIX : Track latence et tokens par transition pour monitoring précis
    # latency_ms: Mapped[float | None] = mapped_column(Float)
    # input_tokens: Mapped[int | None] = mapped_column(Integer)
    # output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── P1: Audit log ───────────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# MODULE RDV — Appointments
# ══════════════════════════════════════════════════════════════════════════════

class BusinessType(enum.StrEnum):
    ECOMMERCE   = "ecommerce"
    APPOINTMENTS = "appointments"
    HYBRID      = "hybrid"          # les deux


class AppointmentStatus(enum.StrEnum):
    PENDING    = "pending"
    CONFIRMED  = "confirmed"
    CANCELLED  = "cancelled"
    COMPLETED  = "completed"
    NO_SHOW    = "no_show"


class ServiceCategory(enum.StrEnum):
    MEDICAL    = "medical"
    BEAUTY     = "beauty"
    LEGAL      = "legal"
    FITNESS    = "fitness"
    RESTAURANT = "restaurant"
    AUTO       = "auto"
    OTHER      = "other"


class DayOfWeek(enum.StrEnum):
    MON = "monday"
    TUE = "tuesday"
    WED = "wednesday"
    THU = "thursday"
    FRI = "friday"
    SAT = "saturday"
    SUN = "sunday"


# ─── BusinessConfig : settings RDV par store ──────────────────────────────────
class BusinessConfig(Base):
    """Config métier d'un store : type d'activité, services, paramètres RDV."""
    __tablename__ = "business_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), unique=True, index=True
    )
    business_type: Mapped[BusinessType] = mapped_column(
        SAEnum(BusinessType, values_callable=lambda x: [e.value for e in x]), default=BusinessType.ECOMMERCE
    )
    service_category: Mapped[ServiceCategory | None] = mapped_column(
        SAEnum(ServiceCategory, values_callable=lambda x: [e.value for e in x])
    )
    # Durée par défaut d'un RDV en minutes
    default_slot_duration_min: Mapped[int] = mapped_column(Integer, default=30)
    # Message de confirmation RDV (template, peut contenir {date}, {time}, {service})
    appointment_confirm_msg: Mapped[str | None] = mapped_column(Text)
    # Message de rappel 24h avant
    appointment_reminder_msg: Mapped[str | None] = mapped_column(Text)
    # Délai min avant réservation (en heures)
    booking_lead_time_hours: Mapped[int] = mapped_column(Integer, default=1)
    # Nb max de RDV par jour
    max_appointments_per_day: Mapped[int | None] = mapped_column(Integer)
    # Adresse / lieu
    address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    store: Mapped["Store"] = relationship("Store", back_populates="business_config")
    services: Mapped[list["Service"]] = relationship("Service", back_populates="business_config")
    availability_rules: Mapped[list["AvailabilityRule"]] = relationship(
        "AvailabilityRule", back_populates="business_config"
    )


# ─── Service : prestation proposée ────────────────────────────────────────────
class Service(Base):
    """Un service réservable (ex: consultation, coupe, bilan, etc.)."""
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_config_id: Mapped[int] = mapped_column(
        ForeignKey("business_configs.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))       # None = gratuit / à définir
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    business_config: Mapped["BusinessConfig"] = relationship(
        "BusinessConfig", back_populates="services"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment", back_populates="service"
    )


# ─── AvailabilityRule : plages horaires récurrentes ───────────────────────────
class AvailabilityRule(Base):
    """Règle de disponibilité hebdomadaire (ex: lundi 9h-12h, 14h-18h)."""
    __tablename__ = "availability_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_config_id: Mapped[int] = mapped_column(
        ForeignKey("business_configs.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    day_of_week: Mapped[DayOfWeek] = mapped_column(SAEnum(DayOfWeek, values_callable=lambda x: [e.value for e in x]))
    start_time: Mapped[str] = mapped_column(String(5))   # "09:00"
    end_time: Mapped[str] = mapped_column(String(5))     # "12:00"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    business_config: Mapped["BusinessConfig"] = relationship(
        "BusinessConfig", back_populates="availability_rules"
    )


# ─── AvailabilityException : fermetures ponctuelles ──────────────────────────
class AvailabilityException(Base):
    """Fermeture ou ouverture exceptionnelle sur une date précise."""
    __tablename__ = "availability_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    date: Mapped[str] = mapped_column(String(10))        # "2026-05-01"
    is_closed: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(255))


# ─── Appointment : RDV réel ───────────────────────────────────────────────────
class Appointment(Base):
    """Un rendez-vous confirmé ou en attente."""
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    service_id: Mapped[int | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL")
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        SAEnum(AppointmentStatus, values_callable=lambda x: [e.value for e in x]), default=AppointmentStatus.PENDING
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    patient_name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Confirmation WA message id pour tracking
    wa_confirm_msg_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    store: Mapped["Store"] = relationship("Store")
    customer: Mapped["Customer"] = relationship("Customer")
    service: Mapped[Optional["Service"]] = relationship(
        "Service", back_populates="appointments"
    )

    __table_args__ = (
        UniqueConstraint(
            "store_id", "scheduled_at", "service_id",
            name="uq_appointments_store_slot_service"
        ),
    )


# ─── Patch Customer avec la relation appointments ─────────────────────────────
# NOTE: Store relations (business_config, social_post_config, social_posts, payment_links)
# ont été déplacées directement dans la classe Store (Fix P2 — élimination monkey-patch).
Customer.appointments = relationship("Appointment", back_populates="customer")


# ══════════════════════════════════════════════════════════════════════════════
# SOCIAL AI PUBLISHER
# ══════════════════════════════════════════════════════════════════════════════

class SocialPostConfig(Base):
    """Préférences IA par store : voix de marque, style image DALL-E, timing."""
    __tablename__ = "social_post_configs"

    id: Mapped[int]               = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int]         = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), unique=True, index=True)
    brand_name: Mapped[str | None]  = mapped_column(String(128))
    brand_voice: Mapped[str]      = mapped_column(String(32), default="professionnel")
    default_language: Mapped[str] = mapped_column(String(10), default="fr")
    hashtags: Mapped[str | None]    = mapped_column(Text)          # JSON list
    emoji_style: Mapped[str]      = mapped_column(String(16), default="moderate")
    image_style: Mapped[str]      = mapped_column(String(128), default="commercial product photo, clean background, professional lighting")
    image_colors: Mapped[str | None] = mapped_column(String(128))
    watermark_text: Mapped[str | None] = mapped_column(String(64))
    networks_enabled: Mapped[str] = mapped_column(Text, default='["instagram","facebook"]')
    auto_schedule: Mapped[bool]   = mapped_column(Boolean, default=False)
    post_times: Mapped[str | None]  = mapped_column(Text)          # JSON ["09:00","18:00"]
    post_days: Mapped[str | None]   = mapped_column(Text)          # JSON [1,2,3,4,5]
    timezone: Mapped[str]         = mapped_column(String(64), default="Africa/Tunis")
    max_posts_per_day: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    store: Mapped["Store"] = relationship("Store", back_populates="social_post_config")


class SocialPost(Base):
    """Historique de chaque publication (générée par IA ou manuelle)."""
    __tablename__ = "social_posts"

    id: Mapped[int]               = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int]         = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    network: Mapped[str]          = mapped_column(String(20))
    post_type: Mapped[str]        = mapped_column(String(20), default="post")
    status: Mapped[str]           = mapped_column(String(20), default="pending", index=True)
    caption: Mapped[str | None]        = mapped_column(Text)
    image_url: Mapped[str | None]      = mapped_column(Text)
    image_prompt: Mapped[str | None]   = mapped_column(Text)
    external_post_id: Mapped[str | None] = mapped_column(String(128))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None]  = mapped_column(Text)
    source: Mapped[str]           = mapped_column(String(32), default="manual")
    product_id: Mapped[int | None] = mapped_column(Integer)
    celery_task_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    store: Mapped["Store"] = relationship("Store", back_populates="social_posts")


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT LINKS MULTI-PAYS
# ══════════════════════════════════════════════════════════════════════════════
class PaymentLink(Base):
    """Lien de paiement autonome généré par le marchand ou par l'IA."""
    __tablename__ = "payment_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Opaque public identifier used by AI-generated checkout URLs.
    # Nullable keeps historical payment links migration-safe.
    token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)

    # Provider et URL
    # SAFE FIX (PROD): url is nullable to support COD/Cash provider which has no checkout URL.
    # All other providers MUST set a non-empty URL — enforced at application layer (api/v1/payment_links.py).
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="stripe | flouci | cmi | aliapay | nexus | cash")
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    subtotal_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    tax_breakdown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    promotion_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    promotion_breakdown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Statut
    status: Mapped[str] = mapped_column(
        String(50), default="pending", server_default="pending", index=True,
        comment="pending | paid | expired | failed"
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True,
        comment="ID retourné par le provider (idempotence)"
    )

    # Facturation
    invoice_url: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="URL du PDF facture")
    invoice_number: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    invoice_pdf_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Canal et client
    channel: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Canal d'origine: whatsapp | instagram | facebook | manual"
    )
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relations
    store: Mapped["Store"] = relationship("Store", back_populates="payment_links")


class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    to: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaxRate(Base):
    __tablename__ = "tax_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    product_category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    is_zero_rate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    name: Mapped[str] = mapped_column(String(100), default="TVA", server_default="TVA")
    legal_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_from: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    valid_to: Mapped[date_type | None] = mapped_column(Date, nullable=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_tax_rates_lookup", "store_id", "country_code", "product_category", "valid_from"),
    )


class TaxExemption(Base):
    __tablename__ = "tax_exemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(255))
    valid_from: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    valid_to: Mapped[date_type | None] = mapped_column(Date, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", index=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    promotion_type: Mapped[str] = mapped_column(String(30), default="automatic", server_default="automatic", index=True)
    discount_type: Mapped[str] = mapped_column(String(30), default="percentage", server_default="percentage")
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    applies_to: Mapped[str] = mapped_column(String(30), default="all", server_default="all")
    eligible_product_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    eligible_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)
    eligible_brands: Mapped[list | None] = mapped_column(JSON, nullable=True)
    gift_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    gift_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gift_quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100", index=True)
    stackable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    customer_segment: Mapped[str | None] = mapped_column(String(30), nullable=True)
    country_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    channel_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    max_global_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_uses_per_customer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromotionRule(Base):
    __tablename__ = "promotion_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    promotion_id: Mapped[int] = mapped_column(ForeignKey("promotions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(50), default="conditions", server_default="conditions")
    conditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    coupon_kind: Mapped[str] = mapped_column(String(20), default="multi", server_default="multi")
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redemptions_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    per_customer_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("store_id", "code", name="uq_coupons_store_code"),
    )


class PromotionUsage(Base):
    __tablename__ = "promotion_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True, index=True)
    coupon_id: Mapped[int | None] = mapped_column(ForeignKey("coupons.id", ondelete="SET NULL"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    payment_link_id: Mapped[int | None] = mapped_column(ForeignKey("payment_links.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="applied", server_default="applied", index=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountingDocument(Base):
    __tablename__ = "accounting_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    payment_link_id: Mapped[int | None] = mapped_column(ForeignKey("payment_links.id", ondelete="SET NULL"), nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(20), index=True)
    number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    original_document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="issued", server_default="issued")
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    tax_breakdown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



# NOTE: Store.social_post_config, Store.social_posts, Store.payment_links
# sont déclarés directement dans la classe Store ci-dessus (Fix P2).


# ── ACTION 6 : Expense — Spending Tracker persisté ────────────────────────────
class ExpenseCategory(enum.StrEnum):
    supplier  = "supplier"
    fixed     = "fixed"
    marketing = "marketing"
    staff     = "staff"
    logistics = "logistics"
    other     = "other"


class Expense(Base):
    """Dépense business persistée en DB — Spending Tracker V9+."""
    __tablename__ = "expenses"

    id:           Mapped[int]              = mapped_column(Integer, primary_key=True)
    store_id:     Mapped[int]              = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    description:  Mapped[str]             = mapped_column(String(500))
    vendor:       Mapped[str | None]    = mapped_column(String(255))
    amount:       Mapped[Decimal]            = mapped_column(Numeric(12, 4), nullable=False)
    currency:     Mapped[str]             = mapped_column(String(5), default="TND")
    category:     Mapped[ExpenseCategory] = mapped_column(SAEnum(ExpenseCategory), default=ExpenseCategory.other)
    note:         Mapped[str | None]    = mapped_column(Text)
    expense_date: Mapped[date_type]        = mapped_column(Date, nullable=False)
    scanned_from_invoice: Mapped[bool]    = mapped_column(Boolean, default=False)
    created_at:   Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_expenses_store_date", "store_id", "expense_date"),)


# class CustomerIdentity(Base):
#     __tablename__ = "customer_identities"
# 
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     tenant_id: Mapped[int] = mapped_column(Integer, index=True) # Clé d'isolation principale
#     customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
#     unique_id: Mapped[str] = mapped_column(String(255), unique=True, index=True) # UUID ou ID externe
#     source: Mapped[str] = mapped_column(String(50)) # e.g., "whatsapp", "messenger", "instagram"
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
# 
#     customer: Mapped["Customer"] = relationship("Customer", back_populates="identities")
# 
# 
# class ContactEndpoint(Base):
#     __tablename__ = "contact_endpoints"
# 
#     id: Mapped[int] = mapped_column(Integer, primary_key=True)
#     tenant_id: Mapped[int] = mapped_column(Integer, index=True) # Clé d'isolation principale
#     customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
#     channel: Mapped[str] = mapped_column(String(50), index=True) # e.g., "whatsapp", "messenger"
#     address: Mapped[str] = mapped_column(String(255), unique=True, index=True) # e.g., numéro de téléphone, ID Messenger
#     is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
# 
#     customer: Mapped["Customer"] = relationship("Customer", back_populates="endpoints")



# ─── PasswordResetToken : tokens de réinitialisation de mot de passe (DB) ─────
class PasswordResetToken(Base):
    """Token de reset de mot de passe persisté en base de données.

    Avantages par rapport au stockage Redis :
      - Survit aux redémarrages / crash Redis
      - Traçabilité (audit complet)
      - Nettoyage garanti via le job de session cleanup
      - Pas de dépendance Redis pour le flow critique de récupération de compte
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_prt_user_active", "user_id", "used", "expires_at"),
    )
