"""0061_loyalty_wallet_tables

P1.8 — Auto-audit du livrable : `models/loyalty.py` (créé en P1.2 pour
réparer l'import cassé de `services/loyalty_service.py`) définit 4 classes
ORM (`LoyaltyProgram`, `LoyaltyRule`, `LoyaltyAccount`, `LoyaltyLedgerEntry`)
mais aucune migration ne les avait jamais créées sur PostgreSQL — exactement
la même catégorie de bug que celui trouvé et corrigé sur `plan_limits` en
0060 (une classe ORM qui existe en Python mais pas en base réelle). Les
tests passaient malgré tout car `tests/test_loyalty_service.py` crée son
propre schéma SQLite via `Base.metadata.create_all()`, qui masque ce genre
de trou exactement comme documenté dans le changelog P1.5.

`services/loyalty_service.py` n'est actuellement appelé par aucune route
(vérifié : aucun import ailleurs que ses propres tests) — donc ce trou est
resté silencieux. Corrigé maintenant, avant qu'une future route ne s'appuie
dessus et casse en production.

RLS incluse dans la même migration (plutôt que d'attendre une future 0062)
car ces 4 tables portent toutes `store_id` — même famille de risque que 0059.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0061_loyalty_wallet_tables"
down_revision = "0060_plan_limits_multi_duration_pricing"
branch_labels = None
depends_on = None

_RLS_TABLES = ("loyalty_programs", "loyalty_rules", "loyalty_accounts", "loyalty_ledger_entries")


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("loyalty_programs"):
        op.create_table(
            "loyalty_programs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default="Programme fidélité"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("default_points_per_eur", sa.Float(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("store_id", name="uq_loyalty_program_store"),
        )
        op.create_index("ix_loyalty_programs_store_id", "loyalty_programs", ["store_id"])

    if not insp.has_table("loyalty_rules"):
        op.create_table(
            "loyalty_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default="Règle par défaut"),
            sa.Column("points_per_eur", sa.Float(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_loyalty_rules_store_id", "loyalty_rules", ["store_id"])
        op.create_index("ix_loyalty_rules_is_active", "loyalty_rules", ["is_active"])

    if not insp.has_table("loyalty_accounts"):
        op.create_table(
            "loyalty_accounts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("store_id", "customer_id", name="uq_loyalty_account_store_customer"),
        )
        op.create_index("ix_loyalty_accounts_store_id", "loyalty_accounts", ["store_id"])
        op.create_index("ix_loyalty_accounts_customer_id", "loyalty_accounts", ["customer_id"])

    if not insp.has_table("loyalty_ledger_entries"):
        op.create_table(
            "loyalty_ledger_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "account_id",
                sa.Integer(),
                sa.ForeignKey("loyalty_accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("points", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(120), nullable=False),
            sa.Column("idempotency_key", sa.String(255), nullable=False),
            sa.Column("amount_eur", sa.Float(), nullable=True),
            sa.Column(
                "rule_id",
                sa.Integer(),
                sa.ForeignKey("loyalty_rules.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("idempotency_key", name="uq_loyalty_ledger_idempotency_key"),
        )
        op.create_index("ix_loyalty_ledger_entries_account_id", "loyalty_ledger_entries", ["account_id"])
        op.create_index("ix_loyalty_ledger_entries_created_at", "loyalty_ledger_entries", ["created_at"])

    if _is_postgresql():
        for table in ("loyalty_programs", "loyalty_rules", "loyalty_accounts"):
            policy = f"tenant_isolation_{table}"
            op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
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
        # loyalty_ledger_entries n'a pas de store_id propre -> policy par jointure
        policy = "tenant_isolation_loyalty_ledger_entries"
        op.execute(sa.text("ALTER TABLE loyalty_ledger_entries ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text("ALTER TABLE loyalty_ledger_entries FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON loyalty_ledger_entries"))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY {policy} ON loyalty_ledger_entries
                USING (
                    current_setting('app.current_user_role', true) = 'super_admin'
                    OR account_id IN (
                        SELECT id FROM loyalty_accounts
                        WHERE store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                    )
                )
                WITH CHECK (
                    current_setting('app.current_user_role', true) = 'super_admin'
                    OR account_id IN (
                        SELECT id FROM loyalty_accounts
                        WHERE store_id = NULLIF(current_setting('app.current_tenant_id', true), '')::int
                    )
                )
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in ("loyalty_ledger_entries", "loyalty_accounts", "loyalty_rules", "loyalty_programs"):
        if insp.has_table(table):
            op.drop_table(table)
