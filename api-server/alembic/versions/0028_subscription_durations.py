"""Abonnements multi-durée (3/6/12 mois) + blocage automatique + rappels

Revision ID: 0028_subscription_durations
Revises: 0027_maghreb_saas_plans
Create Date: 2026-06-12

Ce que cette migration fait :
  1. Ajoute les colonnes prix 3/6/12 mois à `plan_limits`
  2. Crée `tenant_subscriptions` — abonnements avec durée fixe, suivi rappels, blocage
"""

import sqlalchemy as sa

from alembic import op

revision = "0028_subscription_durations"
down_revision = "0027_maghreb_saas_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── 1. Ajouter colonnes prix multi-durée à plan_limits ────────────────────
    op.add_column("plan_limits", sa.Column(
        "price_3months_dt", sa.Float(), nullable=False, server_default="0",
        comment="Prix abonnement 3 mois en Dinars Tunisiens"
    ))
    op.add_column("plan_limits", sa.Column(
        "price_6months_dt", sa.Float(), nullable=False, server_default="0",
        comment="Prix abonnement 6 mois en Dinars Tunisiens (~10% remise)"
    ))
    op.add_column("plan_limits", sa.Column(
        "price_12months_dt", sa.Float(), nullable=False, server_default="0",
        comment="Prix abonnement 12 mois en Dinars Tunisiens (~2 mois offerts)"
    ))

    # Mise à jour des prix 3/6/12 mois pour chaque plan
    # Starter 19,99 DT/mois  -> 3m: 59 DT | 6m: 97 DT | 12m: 199 DT
    # Business 29,99 DT/mois -> 3m: 89 DT | 6m: 145 DT | 12m: 299 DT
    # Premium 39,99 DT/mois  -> 3m: 119 DT | 6m: 195 DT | 12m: 399 DT
    # Pro WA 59,99 DT/mois   -> 3m: 179 DT | 6m: 290 DT | 12m: 599 DT
    op.execute(sa.text("""
        UPDATE plan_limits SET
            price_3months_dt = CASE plan_code
                WHEN 'starter'      THEN 59.00
                WHEN 'business'     THEN 89.00
                WHEN 'premium'      THEN 119.00
                WHEN 'pro_whatsapp' THEN 179.00
                ELSE price_monthly_dt * 3
            END,
            price_6months_dt = CASE plan_code
                WHEN 'starter'      THEN 97.00
                WHEN 'business'     THEN 145.00
                WHEN 'premium'      THEN 195.00
                WHEN 'pro_whatsapp' THEN 290.00
                ELSE price_monthly_dt * 6 * 0.9
            END,
            price_12months_dt = CASE plan_code
                WHEN 'starter'      THEN 199.00
                WHEN 'business'     THEN 299.00
                WHEN 'premium'      THEN 399.00
                WHEN 'pro_whatsapp' THEN 599.00
                ELSE price_annual_dt
            END
    """))

    # ── 2. Créer tenant_subscriptions ─────────────────────────────────────────
    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan_code",
            sa.String(length=32),
            nullable=False,
            comment="starter | business | premium | pro_whatsapp",
        ),
        sa.Column(
            "duration_months",
            sa.Integer(),
            nullable=False,
            comment="Durée choisie : 3 | 6 | 12 mois",
        ),
        sa.Column("price_paid_dt", sa.Float(), nullable=False, server_default="0",
                  comment="Prix réellement payé en DT"),
        sa.Column("price_paid_usd", sa.Float(), nullable=True,
                  comment="Équivalent USD indicatif"),

        # ── Période ───────────────────────────────────────────────────────────
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),

        # ── Statut ────────────────────────────────────────────────────────────
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
            comment="active | expired | suspended | cancelled",
        ),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Timestamp du blocage automatique à expiration"),

        # ── Rappels ───────────────────────────────────────────────────────────
        sa.Column("reminder_7d_sent_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Rappel J-7 envoyé le"),
        sa.Column("reminder_1d_sent_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Rappel J-1 envoyé le"),

        # ── Meta ──────────────────────────────────────────────────────────────
        sa.Column("notes", sa.Text(), nullable=True,
                  comment="Notes admin (raison override, etc.)"),
        sa.Column("created_by", sa.String(length=64), nullable=True,
                  comment="admin:email | system | api"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_tsub_tenant_id",   "tenant_subscriptions", ["tenant_id"])
    op.create_index("ix_tsub_plan_code",   "tenant_subscriptions", ["plan_code"])
    op.create_index("ix_tsub_status",      "tenant_subscriptions", ["status"])
    op.create_index("ix_tsub_expires_at",  "tenant_subscriptions", ["expires_at"])
    op.create_index("ix_tsub_tenant_status",
                    "tenant_subscriptions", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tsub_tenant_status", table_name="tenant_subscriptions")
    op.drop_index("ix_tsub_expires_at",    table_name="tenant_subscriptions")
    op.drop_index("ix_tsub_status",        table_name="tenant_subscriptions")
    op.drop_index("ix_tsub_plan_code",     table_name="tenant_subscriptions")
    op.drop_index("ix_tsub_tenant_id",     table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")

    op.drop_column("plan_limits", "price_12months_dt")
    op.drop_column("plan_limits", "price_6months_dt")
    op.drop_column("plan_limits", "price_3months_dt")
