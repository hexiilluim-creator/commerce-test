"""Maghreb SaaS plans — plan_limits, tenant_usage, credit_ledger, credit_top_up_packs

Revision ID: 0027_maghreb_saas_plans
Revises: 0026_gin_index_conversation_state
Create Date: 2026-06-12

Ce que cette migration fait :
  1. Crée `plan_limits`         — définition officielle des 4 plans (DT + USD)
  2. Crée `tenant_usage`        — consommation temps réel par tenant et par période
  3. Crée `credit_ledger`       — historique complet crédits IA (consommation, achat, bonus, renouvellement)
  4. Crée `credit_top_up_packs` — catalogue des recharges vendables (5 DT / 20 DT / 35 DT)
  5. Met à jour `saas_plans`    — upsert des 4 nouveaux plans en DT
"""


import sqlalchemy as sa

from alembic import op

revision = "0027_maghreb_saas_plans"
down_revision = "0026"
branch_labels = None
depends_on = None


# ══════════════════════════════════════════════════════════════════════════════
# UPGRADE
# ══════════════════════════════════════════════════════════════════════════════

def upgrade() -> None:

    # ── 1. plan_limits ────────────────────────────────────────────────────────
    # Source de vérité unique pour les quotas par plan.
    # Les colonnes *_dt et *_usd coexistent pour affichage et reporting.
    op.create_table(
        "plan_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "plan_code",
            sa.String(length=32),
            nullable=False,
            comment="starter | business | premium | pro_whatsapp",
        ),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0", comment="Ordre d'affichage (asc)"),

        # ── Tarification ──────────────────────────────────────────────────────
        sa.Column("price_monthly_dt", sa.Float(), nullable=False, server_default="0",
                  comment="Prix mensuel en Dinars Tunisiens"),
        sa.Column("price_monthly_usd", sa.Float(), nullable=False, server_default="0",
                  comment="Équivalent USD indicatif"),
        sa.Column("price_annual_dt", sa.Float(), nullable=False, server_default="0",
                  comment="Prix annuel DT (≈2 mois offerts)"),
        sa.Column("price_annual_usd", sa.Float(), nullable=False, server_default="0"),

        # ── Quotas produits / utilisateurs ───────────────────────────────────
        sa.Column("max_products", sa.Integer(), nullable=False, server_default="50",
                  comment="-1 = illimité"),
        sa.Column("max_users", sa.Integer(), nullable=False, server_default="1"),

        # ── Crédits IA mensuels ───────────────────────────────────────────────
        # 1 msg texte = 1 crédit | 1 msg vocal = 5 crédits | 1 image = 10 crédits
        sa.Column("monthly_ai_credits", sa.Integer(), nullable=False, server_default="500"),

        # ── Feature flags ─────────────────────────────────────────────────────
        sa.Column("whatsapp_enabled", sa.Boolean(), nullable=False, server_default=sa.false(),
                  comment="WhatsApp Business (frais Meta séparés)"),
        sa.Column("crm_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("crm_advanced_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("marketing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("omnichannel_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_followup_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("advanced_stats_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("priority_support_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),

        # ── Canaux sociaux inclus ─────────────────────────────────────────────
        # JSON array: ["messenger","instagram","tiktok","whatsapp"]
        sa.Column("included_channels", sa.JSON(), nullable=True),

        # ── Meta ──────────────────────────────────────────────────────────────
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_plan_limits_plan_code", "plan_limits", ["plan_code"], unique=True)
    op.create_index("ix_plan_limits_rank", "plan_limits", ["rank"], unique=False)
    op.create_index("ix_plan_limits_is_active", "plan_limits", ["is_active"], unique=False)

    # ── 2. tenant_usage ───────────────────────────────────────────────────────
    # Snapshot de consommation mis à jour en temps réel.
    # Une ligne par (tenant_id, period_start) — renouvelée chaque mois.
    op.create_table(
        "tenant_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_code",
            sa.String(length=32),
            nullable=False,
            comment="Plan actif au moment de la période",
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),

        # ── Crédits IA ────────────────────────────────────────────────────────
        sa.Column("ai_credits_allocated", sa.Integer(), nullable=False, server_default="0",
                  comment="Quota du plan + recharges achetées"),
        sa.Column("ai_credits_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_credits_remaining", sa.Integer(), nullable=False, server_default="0"),

        # ── Quotas ressources ─────────────────────────────────────────────────
        sa.Column("products_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("users_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversations_count", sa.Integer(), nullable=False, server_default="0"),

        # ── Alertes ───────────────────────────────────────────────────────────
        sa.Column("alert_80_sent_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Quand l'alerte 80% crédits a été envoyée"),
        sa.Column("alert_100_sent_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Quand l'alerte 100% crédits a été envoyée"),
        sa.Column("ai_blocked_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Timestamp du blocage automatique IA"),
        sa.Column("ai_reactivated_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Timestamp de la réactivation (achat recharge)"),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        sa.UniqueConstraint("tenant_id", "period_start", name="uq_tenant_usage_tenant_period"),
    )
    op.create_index("ix_tenant_usage_tenant_id", "tenant_usage", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_usage_plan_code", "tenant_usage", ["plan_code"], unique=False)
    op.create_index("ix_tenant_usage_period_start", "tenant_usage", ["period_start"], unique=False)
    op.create_index("ix_tenant_usage_period_end", "tenant_usage", ["period_end"], unique=False)
    op.create_index(
        "ix_tenant_usage_tenant_period",
        "tenant_usage",
        ["tenant_id", "period_start", "period_end"],
        unique=False,
    )

    # ── 3. credit_ledger ──────────────────────────────────────────────────────
    # Journal complet de tous les mouvements de crédits IA.
    # Append-only — jamais de UPDATE ni DELETE.
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_type",
            sa.String(length=32),
            nullable=False,
            comment=(
                "allocation   — crédits alloués en début de période\n"
                "consumption  — crédits consommés (msg texte / vocal / image)\n"
                "purchase     — recharge achetée\n"
                "bonus        — crédits offerts (promo, support)\n"
                "renewal      — renouvellement mensuel automatique\n"
                "expiry       — crédits expirés non utilisés\n"
                "refund       — remboursement"
            ),
        ),
        sa.Column("credits_delta", sa.Integer(), nullable=False,
                  comment="Positif = crédit ajouté, Négatif = crédit consommé"),
        sa.Column("credits_balance_after", sa.Integer(), nullable=False,
                  comment="Solde après mouvement"),

        # ── Détail de la consommation IA ──────────────────────────────────────
        sa.Column(
            "ai_message_type",
            sa.String(length=16),
            nullable=True,
            comment="text (1 cr) | audio (5 cr) | image (10 cr)",
        ),
        sa.Column("ai_cost_per_message", sa.Integer(), nullable=True,
                  comment="Coût en crédits de CE message"),

        # ── Référence externe ─────────────────────────────────────────────────
        sa.Column("reference_id", sa.String(length=128), nullable=True,
                  comment="ID de la transaction, conversation, ou recharge"),
        sa.Column("reference_type", sa.String(length=32), nullable=True,
                  comment="conversation | top_up | subscription | manual"),
        sa.Column("top_up_pack_id", sa.Integer(), nullable=True,
                  comment="FK vers credit_top_up_packs si c'est un achat"),
        sa.Column("plan_code", sa.String(length=32), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),

        # ── Meta ──────────────────────────────────────────────────────────────
        sa.Column("created_by", sa.String(length=64), nullable=True,
                  comment="system | admin:{email} | webhook:{provider}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_ledger_tenant_id", "credit_ledger", ["tenant_id"], unique=False)
    op.create_index("ix_credit_ledger_entry_type", "credit_ledger", ["entry_type"], unique=False)
    op.create_index("ix_credit_ledger_created_at", "credit_ledger", ["created_at"], unique=False)
    op.create_index(
        "ix_credit_ledger_tenant_type_created",
        "credit_ledger",
        ["tenant_id", "entry_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_credit_ledger_tenant_period",
        "credit_ledger",
        ["tenant_id", "period_start"],
        unique=False,
    )
    op.create_index("ix_credit_ledger_reference_id", "credit_ledger", ["reference_id"], unique=False)

    # ── 4. credit_top_up_packs ────────────────────────────────────────────────
    # Catalogue des recharges disponibles à l'achat.
    op.create_table(
        "credit_top_up_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pack_code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("credits_amount", sa.Integer(), nullable=False,
                  comment="Nombre de crédits IA accordés"),
        sa.Column("price_dt", sa.Float(), nullable=False,
                  comment="Prix en Dinars Tunisiens"),
        sa.Column("price_usd", sa.Float(), nullable=False,
                  comment="Équivalent USD indicatif"),
        sa.Column("bonus_credits", sa.Integer(), nullable=False, server_default="0",
                  comment="Crédits bonus offerts (promo)"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_top_up_packs_pack_code", "credit_top_up_packs", ["pack_code"], unique=True)
    op.create_index("ix_credit_top_up_packs_is_active", "credit_top_up_packs", ["is_active"], unique=False)

    # ── 5. Seed plan_limits ───────────────────────────────────────────────────
    op.execute(sa.text("""
        INSERT INTO plan_limits (
            plan_code, display_name, rank,
            price_monthly_dt, price_monthly_usd, price_annual_dt, price_annual_usd,
            max_products, max_users, monthly_ai_credits,
            whatsapp_enabled, crm_enabled, crm_advanced_enabled,
            marketing_enabled, omnichannel_enabled, auto_followup_enabled,
            advanced_stats_enabled, priority_support_enabled,
            included_channels, is_active
        ) VALUES
        (
            'starter', 'Starter', 10,
            19.99, 6.50, 199.00, 65.00,
            50, 1, 500,
            false, false, false,
            false, false, false,
            false, false,
            '["messenger","instagram","tiktok"]', true
        ),
        (
            'business', 'Business', 20,
            29.99, 10.00, 299.00, 98.00,
            500, 3, 2000,
            false, true, false,
            false, false, true,
            true, false,
            '["messenger","instagram","tiktok"]', true
        ),
        (
            'premium', 'Premium', 30,
            39.99, 13.00, 399.00, 131.00,
            -1, 10, 5000,
            false, true, true,
            true, false, true,
            true, false,
            '["messenger","instagram","tiktok"]', true
        ),
        (
            'pro_whatsapp', 'Pro WhatsApp', 40,
            59.99, 20.00, 599.00, 197.00,
            -1, 20, 10000,
            true, true, true,
            true, true, true,
            true, true,
            '["messenger","instagram","tiktok","whatsapp"]', true
        )
    """))

    # ── 6. Seed credit_top_up_packs ───────────────────────────────────────────
    op.execute(sa.text("""
        INSERT INTO credit_top_up_packs (
            pack_code, display_name, credits_amount,
            price_dt, price_usd, bonus_credits, rank, is_active
        ) VALUES
        ('starter_50',    '50 crédits IA',    50,   25.00, 8.25, 0, 10, true),
        ('growth_200',    '200 crédits IA',   200,  80.00, 26.40, 0, 20, true),
        ('business_500',  '500 crédits IA',   500, 175.00, 57.75, 0, 30, true),
        ('enterprise_1k', '1000 crédits IA', 1000, 300.00, 99.00, 0, 40, true)
    """))


# ══════════════════════════════════════════════════════════════════════════════
# DOWNGRADE
# ══════════════════════════════════════════════════════════════════════════════

def downgrade() -> None:
    op.drop_index("ix_credit_top_up_packs_is_active", table_name="credit_top_up_packs")
    op.drop_index("ix_credit_top_up_packs_pack_code", table_name="credit_top_up_packs")
    op.drop_table("credit_top_up_packs")

    op.drop_index("ix_credit_ledger_reference_id", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_tenant_period", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_tenant_type_created", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_created_at", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_entry_type", table_name="credit_ledger")
    op.drop_index("ix_credit_ledger_tenant_id", table_name="credit_ledger")
    op.drop_table("credit_ledger")

    op.drop_index("ix_tenant_usage_tenant_period", table_name="tenant_usage")
    op.drop_index("ix_tenant_usage_period_end", table_name="tenant_usage")
    op.drop_index("ix_tenant_usage_period_start", table_name="tenant_usage")
    op.drop_index("ix_tenant_usage_plan_code", table_name="tenant_usage")
    op.drop_index("ix_tenant_usage_tenant_id", table_name="tenant_usage")
    op.drop_table("tenant_usage")

    op.drop_index("ix_plan_limits_is_active", table_name="plan_limits")
    op.drop_index("ix_plan_limits_rank", table_name="plan_limits")
    op.drop_index("ix_plan_limits_plan_code", table_name="plan_limits")
    op.drop_table("plan_limits")
