"""merge_all_heads

Revision ID: b09e4521bd0c
Revises: 0035_password_reset_tokens, f2c7cdda776d, f90527dce0c7
Create Date: 2026-06-16 18:01:56.527767

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b09e4521bd0c'
down_revision: Union[str, None] = ('0035_password_reset_tokens', 'f2c7cdda776d', 'f90527dce0c7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
