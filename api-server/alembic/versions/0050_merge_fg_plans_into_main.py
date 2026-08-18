"""0050_merge_fg_plans_into_main — Merge branch Plans A→F into main chain.

RAISON :
  Les migrations 0043–0049 (Plans A TVA, B Promotions, E1 Visual Builder,
  E2 Predictive Restocking, E3 Loyalty IA, F B2B Portal) ont été créées en
  branche séparée. Cette migration de merge consolide en un seul head :
    0042_merge_all_final_heads  (branche principale)
    0049_plan_f_b2b_portal      (branche Plans A→F)
  → Résultat : 1 unique head 0050_merge_fg_plans_into_main.

  Pas d'opération DDL — merge-only.

Revision ID  : 0050_merge_fg_plans_into_main
Revises      : 0042_merge_all_final_heads, 0049_plan_f_b2b_portal
Create Date  : 2026-06-29
"""
from __future__ import annotations

from alembic import op

revision = "0050_merge_fg_plans_into_main"

down_revision = (
    "0042_merge_all_final_heads",
    "0049_plan_f_b2b_portal",
)

branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge-only — aucune opération DDL."""
    pass


def downgrade() -> None:
    """Merge-only — aucune opération DDL."""
    pass
