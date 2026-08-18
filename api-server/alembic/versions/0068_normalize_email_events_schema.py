"""Normalize email_events schema after 0067.

Revision ID: 0068_normalize_email_events_schema
Revises: 0067_enable_email_events_rls
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0068_normalize_email_events_schema"
down_revision: Union[str, Sequence[str], None] = "0067_enable_email_events_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("email_events"):
        op.alter_column(
            "email_events",
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    # Verified on staging to have zero dependent columns. Remove only this
    # orphaned legacy enum so fresh and previously migrated schemas converge.
    op.execute(sa.text("DROP TYPE IF EXISTS public.messagetype"))


def downgrade() -> None:
    # The legacy enum was unused and is intentionally not recreated.
    pass

