"""0049_plan_f_b2b_portal

Revision ID: 0049_plan_f_b2b_portal
Revises: 0048_plan_e_loyalty_ia
Create Date: 2026-06-28

Plan F — B2B Portal
- comptes entreprises (garages / revendeurs / grossistes)
- tarification négociée / dégressive / remises / contrats
- commandes B2B multi-utilisateurs avec validation interne
- facturation groupée, paiement différé, crédit et échéances
"""
import sqlalchemy as sa

from alembic import op

revision = "0049_plan_f_b2b_portal"
down_revision = "0048_plan_e_loyalty_ia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_type", sa.Enum("garage", "reseller", "wholesaler", name="company_account_type"), nullable=False, server_default="garage"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("tax_id", sa.String(length=120), nullable=True),
        sa.Column("billing_email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("status", sa.Enum("prospect", "active", "suspended", name="company_account_status"), nullable=False, server_default="active"),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("store_id", "name", name="uq_company_account_store_name"),
    )
    op.create_index("ix_company_accounts_store_status", "company_accounts", ["store_id", "status"])

    op.create_table(
        "company_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_account_id", sa.Integer(), sa.ForeignKey("company_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("buyer", "manager", "approver", "finance", "admin", name="company_user_role"), nullable=False, server_default="buyer"),
        sa.Column("can_approve", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("company_account_id", "email", name="uq_company_user_email"),
    )
    op.create_index("ix_company_users_store_account", "company_users", ["store_id", "company_account_id"])

    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_account_id", sa.Integer(), sa.ForeignKey("company_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("variant_id", sa.Integer(), sa.ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rule_type", sa.Enum("negotiated", "tiered", "discount", "contract", name="pricing_rule_type"), nullable=False, server_default="discount"),
        sa.Column("contract_code", sa.String(length=80), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("min_qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("negotiated_unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("discount_percent", sa.Numeric(8, 4), nullable=True),
        sa.Column("rebate_percent", sa.Numeric(8, 4), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_pricing_rules_lookup", "pricing_rules", ["store_id", "company_account_id", "product_id", "variant_id"])
    op.create_index("ix_pricing_rules_contract", "pricing_rules", ["store_id", "contract_code"])

    op.create_table(
        "b2b_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_account_id", sa.Integer(), sa.ForeignKey("company_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approval_status", sa.Enum("draft", "pending_approval", "approved", "rejected", "ordered", name="b2b_order_approval_status"), nullable=False, server_default="draft"),
        sa.Column("po_number", sa.String(length=120), nullable=True),
        sa.Column("internal_reference", sa.String(length=120), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("validation_chain", sa.JSON(), nullable=True),
        sa.Column("history", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("invoice_number", sa.String(length=120), nullable=True),
        sa.Column("invoiced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_b2b_orders_store_status", "b2b_orders", ["store_id", "approval_status"])
    op.create_index("ix_b2b_orders_store_company_created", "b2b_orders", ["store_id", "company_account_id", "created_at"])

    op.create_table(
        "b2b_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_account_id", sa.Integer(), sa.ForeignKey("company_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_number", sa.String(length=120), nullable=False),
        sa.Column("grouped_order_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.Enum("draft", "issued", "partially_paid", "paid", "overdue", "cancelled", name="b2b_invoice_status"), nullable=False, server_default="issued"),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("grouped_period_label", sa.String(length=120), nullable=True),
        sa.Column("payment_mode", sa.String(length=32), nullable=False, server_default="deferred"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("subtotal_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("amount_paid", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("store_id", "invoice_number", name="uq_b2b_invoice_store_number"),
    )
    op.create_index("ix_b2b_invoices_store_company_issue", "b2b_invoices", ["store_id", "company_account_id", "issue_date"])
    op.create_index("ix_b2b_invoices_store_status", "b2b_invoices", ["store_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_b2b_invoices_store_status", table_name="b2b_invoices")
    op.drop_index("ix_b2b_invoices_store_company_issue", table_name="b2b_invoices")
    op.drop_table("b2b_invoices")
    op.drop_index("ix_b2b_orders_store_company_created", table_name="b2b_orders")
    op.drop_index("ix_b2b_orders_store_status", table_name="b2b_orders")
    op.drop_table("b2b_orders")
    op.drop_index("ix_pricing_rules_contract", table_name="pricing_rules")
    op.drop_index("ix_pricing_rules_lookup", table_name="pricing_rules")
    op.drop_table("pricing_rules")
    op.drop_index("ix_company_users_store_account", table_name="company_users")
    op.drop_table("company_users")
    op.drop_index("ix_company_accounts_store_status", table_name="company_accounts")
    op.drop_table("company_accounts")
