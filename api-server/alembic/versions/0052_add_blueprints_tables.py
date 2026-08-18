"""0052_add_blueprints_tables — Crée les tables blueprints et store_blueprints.

Revision ID: 0052_add_blueprints_tables
Revises: 0051_runtime_alignment_fixes
Create Date: 2026-07-12

Contexte (audit) :
  Les modèles ORM Blueprint / StoreBlueprint (models/blueprints.py) et le
  router associé (api/v1/blueprints.py, monté dans api/v1/__init__.py)
  existent depuis plusieurs versions, mais aucune migration Alembic ne
  créait leurs tables. Résultat vérifié en PostgreSQL après
  `alembic upgrade head` : les tables `blueprints` et `store_blueprints`
  sont absentes, ce qui fait planter tout appel aux endpoints
  /api/v1/blueprints* en environnement réel (relation does not exist).

  Cette migration corrige ce drift schéma/code.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0052_add_blueprints_tables"
down_revision = "0051_runtime_alignment_fixes"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.Connection, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "blueprints"):
        op.create_table(
            "blueprints",
            sa.Column("id", sa.String(length=50), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("icon", sa.String(length=10), nullable=True),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("modules_enabled", sa.JSON(), nullable=True),
            sa.Column("default_ai_prompt", sa.String(length=2000), nullable=True),
            sa.Column("default_business_type", sa.String(length=50), nullable=True),
            sa.Column("default_service_category", sa.String(length=50), nullable=True),
            sa.Column("ui_visibility", sa.JSON(), nullable=True),
            sa.Column("quotas", sa.JSON(), nullable=True),
            sa.Column("initial_data", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not _table_exists(bind, "store_blueprints"):
        op.create_table(
            "store_blueprints",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("store_id", sa.Integer(), nullable=False, unique=True),
            sa.Column("blueprint_id", sa.String(length=50), nullable=False),
            sa.Column("custom_config", sa.JSON(), nullable=True),
            sa.Column("selected_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["blueprint_id"], ["blueprints.id"],
                name="fk_store_blueprints_blueprint_id",
                ondelete="RESTRICT",
            ),
        )
        op.create_index(
            "ix_store_blueprints_blueprint_id",
            "store_blueprints",
            ["blueprint_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "store_blueprints"):
        op.drop_index("ix_store_blueprints_blueprint_id", table_name="store_blueprints")
        op.drop_table("store_blueprints")
    if _table_exists(bind, "blueprints"):
        op.drop_table("blueprints")
