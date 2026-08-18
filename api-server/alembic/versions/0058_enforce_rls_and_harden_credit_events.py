"""0058_enforce_rls_and_harden_credit_events

Hardening security release:
- Enforce PostgreSQL RLS policies on sensitive multi-tenant tables.
- Expand credit_events event types to match the runtime ledger implementation.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0058_enforce_rls_and_harden_credit_events"
down_revision = "0057_repair_critical_schema_drift"
branch_labels = None
depends_on = None


_TABLES = (
    "orders",
    "products",
    "customers",
    "audit_logs",
    "credit_events",
)


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgresql():
        op.drop_constraint("ck_credit_events_event_type", "credit_events", type_="check")
        op.create_check_constraint(
            "ck_credit_events_event_type",
            "credit_events",
            "event_type IN ('allocate', 'bonus', 'deduct', 'expire', 'refund', 'renewal', 'reset', 'top_up', 'usage')",
        )

        for table in _TABLES:
            op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

        # Tables transactionnelles : une seule policy FOR ALL couvre
        # SELECT/INSERT/UPDATE/DELETE sur le périmètre du tenant.
        for table in ("orders", "products", "customers"):
            policy = f"tenant_isolation_{table}"
            op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
            op.execute(
                sa.text(
                    f"""
                    CREATE POLICY {policy} ON {table}
                    USING (
                        current_setting('app.current_user_role', true) = 'super_admin'
                        OR store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                    )
                    WITH CHECK (
                        current_setting('app.current_user_role', true) = 'super_admin'
                        OR store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                    )
                    """
                )
            )

        # Tables append-only (audit_logs, credit_events) : le tenant ne peut que
        # lire son périmètre (SELECT) et insérer de nouvelles lignes (INSERT) —
        # jamais UPDATE/DELETE. L'ancienne policy FOR ALL est remplacée par deux
        # policies distinctes : FOR SELECT (clause USING uniquement) et
        # FOR INSERT (clause WITH CHECK uniquement).
        append_only_policies = {
            "audit_logs": {
                "SELECT": ("tenant_isolation_audit_logs_select", "USING"),
                "INSERT": ("tenant_isolation_audit_logs_insert", "WITH CHECK"),
            },
            "credit_events": {
                "SELECT": ("tenant_isolation_credit_events_select", "USING"),
                "INSERT": ("tenant_isolation_credit_events_insert", "WITH CHECK"),
            },
        }
        for table, commands in append_only_policies.items():
            for command, (policy, clause) in commands.items():
                op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
                op.execute(
                    sa.text(
                        f"""
                        CREATE POLICY {policy} ON {table}
                        FOR {command}
                        {clause} (
                            current_setting('app.current_user_role', true) = 'super_admin'
                            OR store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                        )
                        """
                    )
                )
    else:
        try:
            op.drop_constraint("ck_credit_events_event_type", "credit_events", type_="check")
        except Exception:
            pass
        op.create_check_constraint(
            "ck_credit_events_event_type",
            "credit_events",
            "event_type IN ('allocate', 'bonus', 'deduct', 'expire', 'refund', 'renewal', 'reset', 'top_up', 'usage')",
        )


def downgrade() -> None:
    if _is_postgresql():
        # Policies SELECT/INSERT propres aux tables append-only.
        for table in ("audit_logs", "credit_events"):
            for policy in (
                f"tenant_isolation_{table}_select",
                f"tenant_isolation_{table}_insert",
            ):
                op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))

        # Policies FOR ALL des tables transactionnelles.
        for table in ("orders", "products", "customers"):
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}"))
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))

    op.drop_constraint("ck_credit_events_event_type", "credit_events", type_="check")
    op.create_check_constraint(
        "ck_credit_events_event_type",
        "credit_events",
        "event_type IN ('allocate', 'deduct', 'topup', 'expire', 'reset', 'refund')",
    )
