"""0018_payment_links_multi_country — PaymentLink table + Store.country + Store.onboarding_completed

Revision ID: 0018_payment_links_multi_country
Revises: 0017_mfa_and_rgpd
Create Date: 2026-04-27

Adds:
  - stores.country (ISO 3166-1 alpha-2, ex: "TN", "AE", "MA", "DZ")
  - stores.onboarding_completed (boolean)
  - table payment_links (liens de paiement autonomes multi-pays)
"""
import sqlalchemy as sa

from alembic import op

revision = "0018_pay_links"
down_revision = "0017_mfa_and_rgpd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Ajout de country et onboarding_completed sur stores ──────────────────
    op.add_column(
        "stores",
        sa.Column("country", sa.String(2), nullable=True, comment="ISO 3166-1 alpha-2 (TN, AE, MA, DZ, ...)"),
    )
    op.add_column(
        "stores",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="True si le marchand a finalisé la configuration du provider de paiement",
        ),
    )

    # ── Table payment_links ───────────────────────────────────────────────────
    op.create_table(
        "payment_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("provider", sa.String(50), nullable=False, comment="stripe | flouci | cmi | aliapay | nexus"),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
            comment="pending | paid | expired | failed",
        ),
        sa.Column("external_reference", sa.String(255), nullable=True, unique=True, comment="ID retourné par le provider"),
        sa.Column("invoice_url", sa.String(1000), nullable=True, comment="URL du PDF facture généré"),
        sa.Column("invoice_number", sa.String(100), nullable=True, unique=True),
        sa.Column(
            "channel",
            sa.String(50),
            nullable=True,
            comment="Canal d'origine de la vente: whatsapp | instagram | facebook | manual",
        ),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True, comment="Date d'envoi du lien au client"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True, comment="Date de paiement confirmé"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Index sur le statut pour les requêtes de dashboard
    op.create_index("ix_payment_links_status", "payment_links", ["status"])
    op.create_index("ix_payment_links_created_at", "payment_links", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_links_created_at", table_name="payment_links")
    op.drop_index("ix_payment_links_status", table_name="payment_links")
    op.drop_table("payment_links")
    op.drop_column("stores", "onboarding_completed")
    op.drop_column("stores", "country")
