"""0057_repair_critical_schema_drift — Répare les tables critiques manquantes.

Revision ID: 0057_repair_critical_schema_drift
Revises: 0056_add_payment_provider_enum
Create Date: 2026-07-17

Contexte
--------
Sur certains environnements, une suite de migrations interrompue a laissé une
base partiellement appliquée :
  - `plan_limits` absente (bloquant la facturation / les abonnements)
  - `tenant_subscriptions` absente ou incomplète
  - `orders` absente, ce qui casse les métriques et certains endpoints admin

Cette migration est volontairement idempotente et défensive :
  - crée les tables critiques si elles sont absentes ;
  - complète les colonnes/index attendus pour `plan_limits` ;
  - seed le catalogue SaaS minimal si nécessaire ;
  - recrée les index critiques utilisés par la pagination / analytics.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0057_repair_critical_schema_drift"
down_revision = "0056_add_payment_provider_enum"
branch_labels = None
depends_on = None


_ORDERSTATUS_VALUES = (
    "pending", "confirmed", "paid", "shipped",
    "delivered", "cancelled", "returned", "refunded",
)
_PAYMENTPROVIDER_VALUES = (
    "flouci", "clix", "tnpay", "cash", "stripe", "cmi", "aliapay", "nexus",
)


_PLAN_ROWS = [
    {
        "plan_code": "starter",
        "display_name": "Starter",
        "rank": 10,
        "price_monthly_dt": 19.99,
        "price_monthly_usd": 6.50,
        "price_annual_dt": 199.00,
        "price_annual_usd": 65.00,
        "price_3months_dt": 59.00,
        "price_6months_dt": 97.00,
        "price_12months_dt": 199.00,
        "max_products": 50,
        "max_users": 1,
        "monthly_ai_credits": 500,
        "whatsapp_enabled": False,
        "crm_enabled": False,
        "crm_advanced_enabled": False,
        "marketing_enabled": False,
        "omnichannel_enabled": False,
        "auto_followup_enabled": False,
        "advanced_stats_enabled": False,
        "priority_support_enabled": False,
        "included_channels": [],
        "is_active": True,
    },
    {
        "plan_code": "business",
        "display_name": "Business",
        "rank": 20,
        "price_monthly_dt": 29.99,
        "price_monthly_usd": 9.75,
        "price_annual_dt": 299.00,
        "price_annual_usd": 97.50,
        "price_3months_dt": 89.00,
        "price_6months_dt": 145.00,
        "price_12months_dt": 299.00,
        "max_products": 250,
        "max_users": 3,
        "monthly_ai_credits": 1500,
        "whatsapp_enabled": False,
        "crm_enabled": True,
        "crm_advanced_enabled": False,
        "marketing_enabled": True,
        "omnichannel_enabled": False,
        "auto_followup_enabled": False,
        "advanced_stats_enabled": True,
        "priority_support_enabled": False,
        "included_channels": ["messenger", "instagram"],
        "is_active": True,
    },
    {
        "plan_code": "premium",
        "display_name": "Premium",
        "rank": 30,
        "price_monthly_dt": 39.99,
        "price_monthly_usd": 13.00,
        "price_annual_dt": 399.00,
        "price_annual_usd": 130.00,
        "price_3months_dt": 119.00,
        "price_6months_dt": 195.00,
        "price_12months_dt": 399.00,
        "max_products": 1000,
        "max_users": 10,
        "monthly_ai_credits": 5000,
        "whatsapp_enabled": True,
        "crm_enabled": True,
        "crm_advanced_enabled": True,
        "marketing_enabled": True,
        "omnichannel_enabled": True,
        "auto_followup_enabled": True,
        "advanced_stats_enabled": True,
        "priority_support_enabled": True,
        "included_channels": ["messenger", "instagram", "tiktok", "whatsapp"],
        "is_active": True,
    },
    {
        "plan_code": "pro_whatsapp",
        "display_name": "Pro WhatsApp",
        "rank": 40,
        "price_monthly_dt": 59.99,
        "price_monthly_usd": 19.50,
        "price_annual_dt": 599.00,
        "price_annual_usd": 195.00,
        "price_3months_dt": 179.00,
        "price_6months_dt": 290.00,
        "price_12months_dt": 599.00,
        "max_products": -1,
        "max_users": 25,
        "monthly_ai_credits": 12000,
        "whatsapp_enabled": True,
        "crm_enabled": True,
        "crm_advanced_enabled": True,
        "marketing_enabled": True,
        "omnichannel_enabled": True,
        "auto_followup_enabled": True,
        "advanced_stats_enabled": True,
        "priority_support_enabled": True,
        "included_channels": ["messenger", "instagram", "tiktok", "whatsapp"],
        "is_active": True,
    },
]


def _table_exists(bind: sa.Connection, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _column_exists(bind: sa.Connection, table_name: str, column_name: str) -> bool:
    try:
        return any(c["name"] == column_name for c in sa.inspect(bind).get_columns(table_name))
    except Exception:
        return False


def _index_exists(bind: sa.Connection, table_name: str, index_name: str) -> bool:
    try:
        return any(ix.get("name") == index_name for ix in sa.inspect(bind).get_indexes(table_name))
    except Exception:
        return False


def _ensure_orderstatus_enum(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus') THEN
                        CREATE TYPE orderstatus AS ENUM (
                            'pending', 'confirmed', 'paid', 'shipped',
                            'delivered', 'cancelled', 'returned', 'refunded'
                        );
                    END IF;
                END
                $$;
                """
            )
        )
        for value in ("returned", "refunded"):
            op.execute(sa.text(f"ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS '{value}'"))


def _ensure_paymentprovider_enum(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    enum_type = postgresql.ENUM(*_PAYMENTPROVIDER_VALUES, name="paymentprovider")
    enum_type.create(bind, checkfirst=True)


def _ensure_orders_table(bind: sa.Connection) -> None:
    _ensure_orderstatus_enum(bind)
    _ensure_paymentprovider_enum(bind)

    status_type: sa.TypeEngine
    payment_provider_type: sa.TypeEngine
    if bind.dialect.name == "postgresql":
        status_type = postgresql.ENUM(*_ORDERSTATUS_VALUES, name="orderstatus", create_type=False)
        payment_provider_type = postgresql.ENUM(*_PAYMENTPROVIDER_VALUES, name="paymentprovider", create_type=False)
    else:
        status_type = sa.String(length=20)
        payment_provider_type = sa.String(length=20)

    if not _table_exists(bind, "orders"):
        op.create_table(
            "orders",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
            sa.Column("status", status_type, nullable=False, server_default=(sa.text("'pending'::orderstatus") if bind.dialect.name == "postgresql" else sa.text("'pending'"))),
            sa.Column("items", sa.JSON(), nullable=False),
            sa.Column("total_amount", sa.Numeric(12, 4), nullable=False),
            sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=True),
            sa.Column("tax_amount", sa.Numeric(12, 4), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("country_code", sa.String(length=2), nullable=True),
            sa.Column("tax_breakdown", sa.JSON(), nullable=True),
            sa.Column("discount_amount", sa.Numeric(12, 4), nullable=True),
            sa.Column("promotion_codes", sa.JSON(), nullable=True),
            sa.Column("promotion_breakdown", sa.JSON(), nullable=True),
            sa.Column("payment_provider", payment_provider_type, nullable=True),
            sa.Column("payment_transaction_id", sa.String(length=255), nullable=True),
            sa.Column("payment_event_id", sa.String(length=255), nullable=True),
            sa.Column("delivery_address", sa.Text(), nullable=True),
            sa.Column("delivery_name", sa.String(length=255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # Compléter les colonnes ajoutées après 0001 si la table existe mais est incomplète.
    missing_columns: list[tuple[str, sa.Column]] = [
        ("subtotal_amount", sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=True)),
        ("tax_amount", sa.Column("tax_amount", sa.Numeric(12, 4), nullable=True)),
        ("currency", sa.Column("currency", sa.String(length=3), nullable=True)),
        ("country_code", sa.Column("country_code", sa.String(length=2), nullable=True)),
        ("tax_breakdown", sa.Column("tax_breakdown", sa.JSON(), nullable=True)),
        ("discount_amount", sa.Column("discount_amount", sa.Numeric(12, 4), nullable=True)),
        ("promotion_codes", sa.Column("promotion_codes", sa.JSON(), nullable=True)),
        ("promotion_breakdown", sa.Column("promotion_breakdown", sa.JSON(), nullable=True)),
    ]
    for column_name, column in missing_columns:
        if _table_exists(bind, "orders") and not _column_exists(bind, "orders", column_name):
            op.add_column("orders", column)

    if not _index_exists(bind, "orders", "ix_orders_store_id"):
        op.create_index("ix_orders_store_id", "orders", ["store_id"], unique=False)
    if not _index_exists(bind, "orders", "ix_orders_customer_id"):
        op.create_index("ix_orders_customer_id", "orders", ["customer_id"], unique=False)
    if not _index_exists(bind, "orders", "ix_orders_payment_event_id"):
        op.create_index("ix_orders_payment_event_id", "orders", ["payment_event_id"], unique=True)
    if not _index_exists(bind, "orders", "ix_orders_created_at"):
        op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    if not _index_exists(bind, "orders", "ix_orders_store_status_created_at"):
        op.create_index("ix_orders_store_status_created_at", "orders", ["store_id", "status", "created_at"], unique=False)
    if not _index_exists(bind, "orders", "ix_orders_store_customer_created_at"):
        op.create_index("ix_orders_store_customer_created_at", "orders", ["store_id", "customer_id", "created_at"], unique=False)
    if not _index_exists(bind, "orders", "ix_orders_store_id_created_at"):
        op.create_index("ix_orders_store_id_created_at", "orders", ["store_id", "created_at"], unique=False)


def _ensure_plan_limits_table(bind: sa.Connection) -> None:
    if not _table_exists(bind, "plan_limits"):
        op.create_table(
            "plan_limits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("plan_code", sa.String(length=32), nullable=False),
            sa.Column("display_name", sa.String(length=64), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("price_monthly_dt", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price_monthly_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price_annual_dt", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price_annual_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price_3months_dt", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price_6months_dt", sa.Float(), nullable=False, server_default="0"),
            sa.Column("price_12months_dt", sa.Float(), nullable=False, server_default="0"),
            sa.Column("max_products", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("max_users", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("monthly_ai_credits", sa.Integer(), nullable=False, server_default="500"),
            sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("crm_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("crm_advanced_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("marketing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("omnichannel_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("auto_followup_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("advanced_stats_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("priority_support_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("included_channels", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    for column_name, column in [
        ("price_3months_dt", sa.Column("price_3months_dt", sa.Float(), nullable=False, server_default="0")),
        ("price_6months_dt", sa.Column("price_6months_dt", sa.Float(), nullable=False, server_default="0")),
        ("price_12months_dt", sa.Column("price_12months_dt", sa.Float(), nullable=False, server_default="0")),
    ]:
        if not _column_exists(bind, "plan_limits", column_name):
            op.add_column("plan_limits", column)

    if not _index_exists(bind, "plan_limits", "ix_plan_limits_plan_code"):
        op.create_index("ix_plan_limits_plan_code", "plan_limits", ["plan_code"], unique=True)
    if not _index_exists(bind, "plan_limits", "ix_plan_limits_rank"):
        op.create_index("ix_plan_limits_rank", "plan_limits", ["rank"], unique=False)
    if not _index_exists(bind, "plan_limits", "ix_plan_limits_is_active"):
        op.create_index("ix_plan_limits_is_active", "plan_limits", ["is_active"], unique=False)

    for row in _PLAN_ROWS:
        exists = bind.execute(
            sa.text("SELECT 1 FROM plan_limits WHERE plan_code = :plan_code LIMIT 1"),
            {"plan_code": row["plan_code"]},
        ).scalar()
        if exists:
            continue
        plan_limits = sa.table(
            "plan_limits",
            sa.column("plan_code", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("rank", sa.Integer()),
            sa.column("price_monthly_dt", sa.Float()),
            sa.column("price_monthly_usd", sa.Float()),
            sa.column("price_annual_dt", sa.Float()),
            sa.column("price_annual_usd", sa.Float()),
            sa.column("price_3months_dt", sa.Float()),
            sa.column("price_6months_dt", sa.Float()),
            sa.column("price_12months_dt", sa.Float()),
            sa.column("max_products", sa.Integer()),
            sa.column("max_users", sa.Integer()),
            sa.column("monthly_ai_credits", sa.Integer()),
            sa.column("whatsapp_enabled", sa.Boolean()),
            sa.column("crm_enabled", sa.Boolean()),
            sa.column("crm_advanced_enabled", sa.Boolean()),
            sa.column("marketing_enabled", sa.Boolean()),
            sa.column("omnichannel_enabled", sa.Boolean()),
            sa.column("auto_followup_enabled", sa.Boolean()),
            sa.column("advanced_stats_enabled", sa.Boolean()),
            sa.column("priority_support_enabled", sa.Boolean()),
            sa.column("included_channels", sa.JSON()),
            sa.column("is_active", sa.Boolean()),
        )
        payload = dict(row)
        payload["included_channels"] = json.loads(json.dumps(payload["included_channels"]))
        op.execute(plan_limits.insert().values(**payload))


def _ensure_tenant_subscriptions_table(bind: sa.Connection) -> None:
    if not _table_exists(bind, "tenant_subscriptions"):
        op.create_table(
            "tenant_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_code", sa.String(length=32), nullable=False),
            sa.Column("duration_months", sa.Integer(), nullable=False),
            sa.Column("price_paid_dt", sa.Numeric(12, 4), nullable=False, server_default="0"),
            sa.Column("price_paid_usd", sa.Numeric(12, 4), nullable=True),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reminder_7d_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reminder_1d_sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    for index_name, columns in [
        ("ix_tsub_tenant_id", ["tenant_id"]),
        ("ix_tsub_plan_code", ["plan_code"]),
        ("ix_tsub_status", ["status"]),
        ("ix_tsub_expires_at", ["expires_at"]),
        ("ix_tsub_tenant_status", ["tenant_id", "status"]),
    ]:
        if not _index_exists(bind, "tenant_subscriptions", index_name):
            op.create_index(index_name, "tenant_subscriptions", columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_orders_table(bind)
    _ensure_plan_limits_table(bind)
    _ensure_tenant_subscriptions_table(bind)


def downgrade() -> None:
    # Migration de réparation : downgrade volontairement non destructif.
    pass
