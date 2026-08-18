"""0044_plan_a_tax_and_billing

Revision ID: 0044_plan_a_tax_and_billing
Revises: 0043_user_role_constraint
Create Date: 2026-06-28

Plan A — Internationalisation fiscale & paiement :
- TVA multi-pays par store/pays/catégorie + historique + exonérations
- enrichissement order/payment_links pour HT/TVA/TTC + traçabilité provider
- documents comptables (factures / avoirs)
"""
import sqlalchemy as sa

from alembic import op

revision = "0044_plan_a_tax_and_billing"
down_revision = "0043_user_role_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── stores ────────────────────────────────────────────────────────────────
    op.add_column("stores", sa.Column("vat_number", sa.String(length=64), nullable=True))
    op.add_column("stores", sa.Column("legal_name", sa.String(length=255), nullable=True))
    op.add_column("stores", sa.Column("legal_address", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("invoice_prefix", sa.String(length=10), nullable=False, server_default="INV"))
    op.add_column("stores", sa.Column("credit_note_prefix", sa.String(length=10), nullable=False, server_default="AV"))
    op.add_column("stores", sa.Column("default_tax_country", sa.String(length=2), nullable=True))
    op.add_column("stores", sa.Column("tax_inclusive_pricing", sa.Boolean(), nullable=False, server_default=sa.text("true")))

    # ── products ──────────────────────────────────────────────────────────────
    op.add_column("products", sa.Column("tax_category", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("is_tax_exempt", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # ── orders ────────────────────────────────────────────────────────────────
    op.add_column("orders", sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("orders", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column("orders", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.add_column("orders", sa.Column("tax_breakdown", sa.JSON(), nullable=True))

    # ── payment_links ─────────────────────────────────────────────────────────
    op.add_column("payment_links", sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("payment_links", sa.Column("tax_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("payment_links", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.add_column("payment_links", sa.Column("tax_breakdown", sa.JSON(), nullable=True))
    op.add_column("payment_links", sa.Column("invoice_pdf_path", sa.String(length=1000), nullable=True))
    op.add_column("payment_links", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_links", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_links", sa.Column("refunded_amount", sa.Numeric(12, 4), nullable=True))
    op.add_column("payment_links", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("payment_links", sa.Column("provider_payload", sa.JSON(), nullable=True))

    # ── tax_rates ─────────────────────────────────────────────────────────────
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("product_category", sa.String(length=100), nullable=True),
        sa.Column("rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("is_zero_rate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_exempt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("name", sa.String(length=100), nullable=False, server_default="TVA"),
        sa.Column("legal_reference", sa.String(length=255), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tax_rates_lookup", "tax_rates", ["store_id", "country_code", "product_category", "valid_from"])
    op.create_index(op.f("ix_tax_rates_country_code"), "tax_rates", ["country_code"])
    op.create_index(op.f("ix_tax_rates_product_category"), "tax_rates", ["product_category"])
    op.create_index(op.f("ix_tax_rates_valid_from"), "tax_rates", ["valid_from"])
    op.create_index(op.f("ix_tax_rates_valid_to"), "tax_rates", ["valid_to"])

    # ── tax_exemptions ────────────────────────────────────────────────────────
    op.create_table(
        "tax_exemptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("customer_phone", sa.String(length=30), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_tax_exemptions_store_id"), "tax_exemptions", ["store_id"])
    op.create_index(op.f("ix_tax_exemptions_customer_email"), "tax_exemptions", ["customer_email"])
    op.create_index(op.f("ix_tax_exemptions_customer_phone"), "tax_exemptions", ["customer_phone"])
    op.create_index(op.f("ix_tax_exemptions_country_code"), "tax_exemptions", ["country_code"])
    op.create_index(op.f("ix_tax_exemptions_valid_from"), "tax_exemptions", ["valid_from"])
    op.create_index(op.f("ix_tax_exemptions_valid_to"), "tax_exemptions", ["valid_to"])

    # ── accounting_documents ──────────────────────────────────────────────────
    op.create_table(
        "accounting_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_link_id", sa.Integer(), sa.ForeignKey("payment_links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("number", sa.String(length=100), nullable=False, unique=True),
        sa.Column("original_document_number", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="issued"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("tax_breakdown", sa.JSON(), nullable=True),
        sa.Column("pdf_path", sa.String(length=1000), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_accounting_documents_store_id"), "accounting_documents", ["store_id"])
    op.create_index(op.f("ix_accounting_documents_payment_link_id"), "accounting_documents", ["payment_link_id"])
    op.create_index(op.f("ix_accounting_documents_order_id"), "accounting_documents", ["order_id"])
    op.create_index(op.f("ix_accounting_documents_document_type"), "accounting_documents", ["document_type"])
    op.create_index(op.f("ix_accounting_documents_number"), "accounting_documents", ["number"], unique=True)


    # ── backfill global VAT history par défaut ───────────────────────────────
    op.execute(
        """
        INSERT INTO tax_rates (store_id, country_code, product_category, rate, is_zero_rate, is_exempt, name, valid_from, priority, is_active)
        VALUES
          (NULL, 'TN', NULL, 0.1900, false, false, 'TVA', DATE '2020-01-01', 100, true),
          (NULL, 'FR', NULL, 0.2000, false, false, 'TVA', DATE '2020-01-01', 100, true),
          (NULL, 'MA', NULL, 0.2000, false, false, 'TVA', DATE '2020-01-01', 100, true),
          (NULL, 'DZ', NULL, 0.1900, false, false, 'TVA', DATE '2020-01-01', 100, true),
          (NULL, 'AE', NULL, 0.0000, true, false, 'TVA 0%', DATE '2020-01-01', 100, true),
          (NULL, 'SA', NULL, 0.1500, false, false, 'VAT', DATE '2020-01-01', 100, true),
          (NULL, 'EG', NULL, 0.1400, false, false, 'TVA', DATE '2020-01-01', 100, true)
        """
    )

    # Backfill léger pour les commandes/liens historiques
    op.execute(
        "UPDATE orders SET subtotal_amount = total_amount, tax_amount = 0 WHERE subtotal_amount IS NULL"
    )
    op.execute(
        "UPDATE payment_links SET subtotal_amount = amount, tax_amount = 0 WHERE subtotal_amount IS NULL"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_accounting_documents_number"), table_name="accounting_documents")
    op.drop_index(op.f("ix_accounting_documents_document_type"), table_name="accounting_documents")
    op.drop_index(op.f("ix_accounting_documents_order_id"), table_name="accounting_documents")
    op.drop_index(op.f("ix_accounting_documents_payment_link_id"), table_name="accounting_documents")
    op.drop_index(op.f("ix_accounting_documents_store_id"), table_name="accounting_documents")
    op.drop_table("accounting_documents")

    op.drop_index(op.f("ix_tax_exemptions_valid_to"), table_name="tax_exemptions")
    op.drop_index(op.f("ix_tax_exemptions_valid_from"), table_name="tax_exemptions")
    op.drop_index(op.f("ix_tax_exemptions_country_code"), table_name="tax_exemptions")
    op.drop_index(op.f("ix_tax_exemptions_customer_phone"), table_name="tax_exemptions")
    op.drop_index(op.f("ix_tax_exemptions_customer_email"), table_name="tax_exemptions")
    op.drop_index(op.f("ix_tax_exemptions_store_id"), table_name="tax_exemptions")
    op.drop_table("tax_exemptions")

    op.drop_index(op.f("ix_tax_rates_valid_to"), table_name="tax_rates")
    op.drop_index(op.f("ix_tax_rates_valid_from"), table_name="tax_rates")
    op.drop_index(op.f("ix_tax_rates_product_category"), table_name="tax_rates")
    op.drop_index(op.f("ix_tax_rates_country_code"), table_name="tax_rates")
    op.drop_index("ix_tax_rates_lookup", table_name="tax_rates")
    op.drop_table("tax_rates")

    op.drop_column("payment_links", "provider_payload")
    op.drop_column("payment_links", "failure_reason")
    op.drop_column("payment_links", "refunded_amount")
    op.drop_column("payment_links", "last_verified_at")
    op.drop_column("payment_links", "cancelled_at")
    op.drop_column("payment_links", "invoice_pdf_path")
    op.drop_column("payment_links", "tax_breakdown")
    op.drop_column("payment_links", "country_code")
    op.drop_column("payment_links", "tax_amount")
    op.drop_column("payment_links", "subtotal_amount")

    op.drop_column("orders", "tax_breakdown")
    op.drop_column("orders", "country_code")
    op.drop_column("orders", "currency")
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")

    op.drop_column("products", "is_tax_exempt")
    op.drop_column("products", "tax_category")

    op.drop_column("stores", "tax_inclusive_pricing")
    op.drop_column("stores", "default_tax_country")
    op.drop_column("stores", "credit_note_prefix")
    op.drop_column("stores", "invoice_prefix")
    op.drop_column("stores", "legal_address")
    op.drop_column("stores", "legal_name")
    op.drop_column("stores", "vat_number")
