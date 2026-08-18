"""Merge: 0061_loyalty_wallet_tables + 0063_full_rls_audit

Revision ID: 0064_merge_rls_audit_and_loyalty
Revises: 0061_loyalty_wallet_tables, 0063_full_rls_audit
Create Date: 2026-08-05 09:30:06.357324

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0064_merge_rls_audit_and_loyalty'
down_revision: Union[str, None] = ('0061_loyalty_wallet_tables', '0063_full_rls_audit')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
