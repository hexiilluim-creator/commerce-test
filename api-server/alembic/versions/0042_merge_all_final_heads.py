"""0042_merge_all_final_heads — Consolide tous les heads en un seul.

RAISON (CTO Audit — Bloquant B2) :
  La chaîne Alembic présente 5 heads distincts, ce qui bloque tout
  déploiement en production : `alembic upgrade heads` peut produire
  une DB incohérente selon l'ordre d'application.

  Heads fusionnés :
    - 0041_product_images_columns  (branche principale — images/numéraire/RGPD)
    - 0037_rgpd_data_retention     (branche RGPD — aurait dû être dans 0038)
    - 0035_password_reset_tokens   (branche reset tokens — orpheline)
    - f90527dce0c7                 (branche merge intermédiaire)
    - f2c7cdda776d                 (branche omnichannel ext)

  Après cette migration, `alembic heads` retourne exactement 1 résultat :
    0042_merge_all_final_heads

  Pas d'opération DDL — migration de merge pure (upgrade/downgrade = pass).

Revision ID  : 0042_merge_all_final_heads
Revises      : 0041_product_images_columns,
               0037_rgpd_data_retention,
               0035_password_reset_tokens,
               f90527dce0c7,
               f2c7cdda776d
Create Date  : 2026-06-28
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

# ---------------------------------------------------------------------------
# Identifiants de révision Alembic
# ---------------------------------------------------------------------------
revision: str = "0042_merge_all_final_heads"

# Plain tuple — no type annotation — ensures Alembic CLI and our chain verifier
# both parse this correctly (type annotation breaks simple regex matchers).
down_revision = (
    "0041_product_images_columns",
    "0037_rgpd_data_retention",
    "0035_password_reset_tokens",
    "f90527dce0c7",
    "f2c7cdda776d",
)

branch_labels: Union[str, Sequence[str], None] = None
depends_on:    Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge-only migration — aucune opération DDL."""
    pass


def downgrade() -> None:
    """Merge-only migration — aucune opération DDL."""
    pass
