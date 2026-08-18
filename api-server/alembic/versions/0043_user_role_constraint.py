"""0043_user_role_constraint — CHECK constraint on users.role + document RBAC hierarchy.

RAISON (CTO Audit — P1 RBAC):
  users.role est String(50) sans contrainte DB — n'importe quelle valeur
  peut être insérée silencieusement. Ce CHECK constraint garantit que seules
  les quatre rôles connus sont acceptés.

Rôles valides:
  viewer      — lecture seule (dashboards, rapports)
  manager     — gestion orders + products + customers; pas de billing/team
  admin       — accès complet au tenant (défaut propriétaire boutique)
  super_admin — accès plateforme cross-tenant (TenantMiddleware enforced)

Toutes les valeurs existantes en production (admin, super_admin) sont incluses.
Migration idempotente: ne plante pas si la contrainte existe déjà.

Revision ID  : 0043_user_role_constraint
Revises      : 0042_merge_all_final_heads
Create Date  : 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision: str = "0043_user_role_constraint"
down_revision: str = "0042_merge_all_final_heads"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_users_role_valid"
_VALID = ("viewer", "manager", "admin", "super_admin")


def upgrade() -> None:
    # Idempotent: skip if constraint already exists
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM   pg_constraint
                WHERE  conname    = '{_CONSTRAINT}'
                AND    conrelid   = 'users'::regclass
            ) THEN
                ALTER TABLE users
                ADD CONSTRAINT {_CONSTRAINT}
                CHECK (role IN {_VALID!r});
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(f"ALTER TABLE users DROP CONSTRAINT IF EXISTS {_CONSTRAINT};")
