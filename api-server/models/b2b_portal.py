from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from models.database import Base


class CompanyAccountType(enum.StrEnum):
    GARAGE = "garage"
    RESELLER = "reseller"
    WHOLESALER = "wholesaler"


class CompanyAccountStatus(enum.StrEnum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class CompanyUserRole(enum.StrEnum):
    BUYER = "buyer"
    MANAGER = "manager"
    APPROVER = "approver"
    FINANCE = "finance"
    ADMIN = "admin"


class PricingRuleType(enum.StrEnum):
    NEGOTIATED = "negotiated"
    TIERED = "tiered"
    DISCOUNT = "discount"
    CONTRACT = "contract"


class B2BOrderApprovalStatus(enum.StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDERED = "ordered"


class B2BInvoiceStatus(enum.StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class CompanyAccount(Base):
    __tablename__ = "company_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    account_type: Mapped[CompanyAccountType] = mapped_column(
        SAEnum(CompanyAccountType, name="company_account_type", values_callable=lambda x: [e.value for e in x]),
        default=CompanyAccountType.GARAGE,
    )
    name: Mapped[str] = mapped_column(String(255))
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CompanyAccountStatus] = mapped_column(
        SAEnum(CompanyAccountStatus, name="company_account_status", values_callable=lambda x: [e.value for e in x]),
        default=CompanyAccountStatus.ACTIVE,
    )
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users: Mapped[list[CompanyUser]] = relationship("CompanyUser", back_populates="company_account", cascade="all, delete-orphan")
    pricing_rules: Mapped[list[PricingRule]] = relationship("PricingRule", back_populates="company_account", cascade="all, delete-orphan")
    orders: Mapped[list[B2BOrder]] = relationship("B2BOrder", back_populates="company_account")
    invoices: Mapped[list[B2BInvoice]] = relationship("B2BInvoice", back_populates="company_account")

    __table_args__ = (
        UniqueConstraint("store_id", "name", name="uq_company_account_store_name"),
        Index("ix_company_accounts_store_status", "store_id", "status"),
    )


class CompanyUser(Base):
    __tablename__ = "company_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    company_account_id: Mapped[int] = mapped_column(ForeignKey("company_accounts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    role: Mapped[CompanyUserRole] = mapped_column(
        SAEnum(CompanyUserRole, name="company_user_role", values_callable=lambda x: [e.value for e in x]),
        default=CompanyUserRole.BUYER,
    )
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company_account: Mapped[CompanyAccount] = relationship("CompanyAccount", back_populates="users")

    __table_args__ = (
        UniqueConstraint("company_account_id", "email", name="uq_company_user_email"),
        Index("ix_company_users_store_account", "store_id", "company_account_id"),
    )


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    company_account_id: Mapped[int] = mapped_column(ForeignKey("company_accounts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    rule_type: Mapped[PricingRuleType] = mapped_column(
        SAEnum(PricingRuleType, name="pricing_rule_type", values_callable=lambda x: [e.value for e in x]),
        default=PricingRuleType.DISCOUNT,
    )
    contract_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    min_qty: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    negotiated_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    rebate_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terms: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company_account: Mapped[CompanyAccount] = relationship("CompanyAccount", back_populates="pricing_rules")

    __table_args__ = (
        Index("ix_pricing_rules_lookup", "store_id", "company_account_id", "product_id", "variant_id"),
        Index("ix_pricing_rules_contract", "store_id", "contract_code"),
    )


class B2BOrder(Base):
    __tablename__ = "b2b_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    company_account_id: Mapped[int] = mapped_column(ForeignKey("company_accounts.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approval_status: Mapped[B2BOrderApprovalStatus] = mapped_column(
        SAEnum(B2BOrderApprovalStatus, name="b2b_order_approval_status", values_callable=lambda x: [e.value for e in x]),
        default=B2BOrderApprovalStatus.DRAFT,
    )
    po_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    internal_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    items: Mapped[list] = mapped_column(JSON)
    validation_chain: Mapped[list | None] = mapped_column(JSON, nullable=True)
    history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    invoiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company_account: Mapped[CompanyAccount] = relationship("CompanyAccount", back_populates="orders")

    __table_args__ = (
        Index("ix_b2b_orders_store_status", "store_id", "approval_status"),
        Index("ix_b2b_orders_store_company_created", "store_id", "company_account_id", "created_at"),
    )


class B2BInvoice(Base):
    __tablename__ = "b2b_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    company_account_id: Mapped[int] = mapped_column(ForeignKey("company_accounts.id", ondelete="CASCADE"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(120), index=True)
    grouped_order_ids: Mapped[list] = mapped_column(JSON)
    status: Mapped[B2BInvoiceStatus] = mapped_column(
        SAEnum(B2BInvoiceStatus, name="b2b_invoice_status", values_callable=lambda x: [e.value for e in x]),
        default=B2BInvoiceStatus.ISSUED,
    )
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    grouped_period_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_mode: Mapped[str] = mapped_column(String(32), default="deferred", server_default="deferred")
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company_account: Mapped[CompanyAccount] = relationship("CompanyAccount", back_populates="invoices")

    __table_args__ = (
        UniqueConstraint("store_id", "invoice_number", name="uq_b2b_invoice_store_number"),
        Index("ix_b2b_invoices_store_company_issue", "store_id", "company_account_id", "issue_date"),
        Index("ix_b2b_invoices_store_status", "store_id", "status"),
    )
