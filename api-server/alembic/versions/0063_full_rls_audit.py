"""0063_full_rls_audit

Revision ID: 0063_full_rls_audit
Revises: 0059_extend_rls_full_tenant_coverage
"""
from __future__ import annotations

from alembic import op

revision = "0063_full_rls_audit"
down_revision = "0059_extend_rls_full_tenant_coverage"
branch_labels = None
depends_on = None

SQL = """
CREATE OR REPLACE VIEW rls_missing_policies AS
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename NOT IN (
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_policy p ON p.polrelid = c.oid
    WHERE n.nspname = 'public'
  );
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS rls_missing_policies;")
