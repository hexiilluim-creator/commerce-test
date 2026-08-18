"""
models/visual_builder.py — Plan E1 — Visual Catalog Builder.

Tables:
  - visual_build          : one row per catalog item being assembled
  - visual_build_asset    : photos / generated images attached to a build
  - visual_build_review   : human validation snapshot (append-only)
  - visual_build_history  : audit trail (append-only, immutable)
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


class VisualBuildStatus(enum.StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    PUBLISHED = "published"


class VisualBuild(Base):
    __tablename__ = "visual_builds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    locale_default: Mapped[str] = mapped_column(String(8), default="fr", nullable=False)

    # AI-generated artifacts
    description_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_long: Mapped[str | None] = mapped_column(Text, nullable=True)
    bullets: Mapped[str | None] = mapped_column(JSON, default=list)
    seo_title: Mapped[str | None] = mapped_column(String(140), nullable=True)
    seo_meta: Mapped[str | None] = mapped_column(String(320), nullable=True)
    seo_keywords: Mapped[str | None] = mapped_column(JSON, default=list)
    seo_og: Mapped[str | None] = mapped_column(JSON, default=dict)
    seo_score: Mapped[int | None] = mapped_column(Integer, default=0)

    # Translations: { locale: { field: value, ... }, ... }
    translations: Mapped[dict | None] = mapped_column(JSON, default=dict)
    glossary: Mapped[dict | None] = mapped_column(JSON, default=dict)

    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum(VisualBuildStatus, name="visual_build_status"),
        default=VisualBuildStatus.DRAFT,
        index=True,
    )

    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    assets = relationship("VisualBuildAsset", backref="build", cascade="all, delete-orphan")
    reviews = relationship("VisualBuildReview", backref="build", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_visual_builds_store_status", "store_id", "status"),
        UniqueConstraint("store_id", "product_id", "locale_default", name="uq_visual_build_product_locale"),
    )


class VisualBuildAsset(Base):
    __tablename__ = "visual_build_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    build_id: Mapped[int] = mapped_column(
        ForeignKey("visual_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), default="photo")  # photo|enhanced|generated
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_metadata: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VisualBuildReview(Base):
    __tablename__ = "visual_build_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    build_id: Mapped[int] = mapped_column(
        ForeignKey("visual_builds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str] = mapped_column(String(32), default="pending")
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VisualBuildHistory(Base):
    """Append-only audit log. Never updated or deleted via the application."""
    __tablename__ = "visual_build_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    build_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON, default=dict)
    after: Mapped[dict | None] = mapped_column(JSON, default=dict)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_visual_build_history_store_build", "store_id", "build_id"),
    )
