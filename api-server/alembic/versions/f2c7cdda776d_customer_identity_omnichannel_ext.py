"""Stub: CustomerIdentity/ContactEndpoint migrated to 0030_customer_identity_omnichannel

Revision ID: f2c7cdda776d
Revises: 0028_subscription_durations
Create Date: 2026-06-14 10:01:15.289184

NOTE: This migration was superseded by 0030_customer_identity_omnichannel.py which
provides the canonical omnichannel schema. This stub exists to maintain Alembic
chain integrity for databases that may have applied this revision ID.
The actual schema is defined in 0030.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = 'f2c7cdda776d'
down_revision: Union[str, None] = '0028_subscription_durations'  # BUG#9 FIX: reattached to main chain — eliminates 2nd Alembic root
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema changes are handled by 0030_customer_identity_omnichannel.py
    # This stub ensures the revision chain remains intact for older databases
    pass


def downgrade() -> None:
    pass
