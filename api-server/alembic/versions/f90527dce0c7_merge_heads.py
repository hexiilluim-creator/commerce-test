"""merge_heads — resolved: 0034 now follows 0033 linearly

Revision ID: f90527dce0c7
Revises: 0034_enterprise_omnicall
Create Date: 2026-06-15 20:13:58.842895

NOTE: This was a merge migration to reconcile two parallel branches.
After fixing 0034 to follow 0033 directly (not the f2c7 stub),
the chain is linear again. This migration now simply passes through
as the single head after 0034.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = 'f90527dce0c7'
down_revision: Union[str, None] = '0034_enterprise_omnicall'  # FIX: was ('0033','0034') merge — now linear
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass  # merge point — no schema changes


def downgrade() -> None:
    pass
