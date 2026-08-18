"""Structured Agent — Customer fields for emotion and preferences

Revision ID: 0005_structured_agent_fields
Revises: 0004_sprint2_pgvector
Create Date: 2026-04-22 12:00:00

Changes:
  - customers.last_emotion (String 50)
  - customers.preferences (JSON)
"""
import sqlalchemy as sa

from alembic import op

revision = "0005_structured_agent_fields"
down_revision = "0004_sprint2_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('last_emotion', sa.String(length=50), nullable=True))
    op.add_column('customers', sa.Column('preferences', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('customers', 'preferences')
    op.drop_column('customers', 'last_emotion')
