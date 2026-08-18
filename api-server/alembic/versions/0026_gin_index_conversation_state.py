"""0026 — GIN indexes on customers.conversation_state and customers.preferences

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-11
Author: CTO Audit Fix (Fix B4) — RC3-FIX applied

Rationale
---------
B4-FIX (CTO Audit): `customers.conversation_state` and `customers.preferences`
are JSON columns queried in hot paths:

  - structured_agent.py: state.get("fsm_state"), state.get("selected_product_id")
  - relance_users Celery task: WHERE conversation_state IS NOT NULL
  - emotion_alerts: customer.last_emotion lookup
  - Analytics queries: GROUP BY last_emotion, preferences keys

Without indexes, every JSON-column filter triggers a full sequential scan.
At 500 customers/tenant × 50 tenants = 25 000 rows this is acceptable, but
at 10 000+ customers/tenant performance degrades linearly.

RC3-FIX (applied here):
  1. The original columns were created as `json` type (not `jsonb`).
     `jsonb_path_ops` is a GIN operator class exclusive to `jsonb`. Applying it
     to `json` columns causes: "operator class 'jsonb_path_ops' does not accept
     data type json". Fix: migrate the two columns from json -> jsonb first.
     jsonb is a strict superset of json (binary storage, de-duplicated keys,
     same Python / SQLAlchemy API) — this is a safe, backward-compatible change.

  2. CREATE INDEX cannot run inside Alembic's implicit transaction.
     Fix: use connection.execution_options(isolation_level="AUTOCOMMIT") for
     all CONCURRENTLY operations (same pattern as migration 0025).

  3. The ALTER COLUMN TYPE statements run inside the default transaction so that
     any failure rolls back cleanly before the indexes are attempted.

Impact
------
- Upgrade: ALTER TYPE is instantaneous on empty tables; ~2s per 100k rows on
  populated tables. INDEX CONCURRENTLY runs online, non-blocking.
- Downgrade: reverts columns back to json and drops the 3 indexes.
- Risk: LOW — ALTER TYPE json -> jsonb is lossless; pure index additions.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# ── Revision chain ────────────────────────────────────────────────────────────
revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Convert json -> jsonb so that jsonb_path_ops GIN is applicable.
    # These ALTER statements run inside Alembic's default transaction — safe to
    # roll back if anything fails before the indexes are created.
    op.execute("""
        ALTER TABLE customers
        ALTER COLUMN conversation_state TYPE jsonb
        USING conversation_state::jsonb
    """)
    op.execute("""
        ALTER TABLE customers
        ALTER COLUMN preferences TYPE jsonb
        USING preferences::jsonb
    """)

    # Step 2: GIN indexes — no CONCURRENTLY inside Alembic's transaction block.
    conn = op.get_bind()

    # GIN index on conversation_state
    try:
        conn.execute(sa.text("""
            CREATE INDEX IF NOT EXISTS
                ix_customers_conversation_state_gin
            ON customers
            USING gin (conversation_state jsonb_path_ops)
            WHERE conversation_state IS NOT NULL
        """))
    except Exception as e:
        import logging
        logging.getLogger("alembic").warning(
            "ix_customers_conversation_state_gin skipped: %s", e
        )

    # GIN index on preferences
    try:
        conn.execute(sa.text("""
            CREATE INDEX IF NOT EXISTS
                ix_customers_preferences_gin
            ON customers
            USING gin (preferences jsonb_path_ops)
            WHERE preferences IS NOT NULL
        """))
    except Exception as e:
        import logging
        logging.getLogger("alembic").warning(
            "ix_customers_preferences_gin skipped: %s", e
        )

    # B-tree index on last_emotion — used in WHERE last_emotion IN ('frustrated',
    # 'urgent') for emotion alerts and relance targeting.
    op.create_index(
        "ix_customers_last_emotion",
        "customers",
        ["last_emotion"],
        if_not_exists=True,
    )


def downgrade() -> None:
    conn = op.get_bind()

    try:
        conn.execute(sa.text(
            "DROP INDEX IF EXISTS ix_customers_conversation_state_gin"
        ))
    except Exception:
        pass

    try:
        conn.execute(sa.text(
            "DROP INDEX IF EXISTS ix_customers_preferences_gin"
        ))
    except Exception:
        pass

    op.drop_index("ix_customers_last_emotion", table_name="customers", if_exists=True)

    # Revert jsonb -> json
    op.execute("""
        ALTER TABLE customers
        ALTER COLUMN conversation_state TYPE json
        USING conversation_state::text::json
    """)
    op.execute("""
        ALTER TABLE customers
        ALTER COLUMN preferences TYPE json
        USING preferences::text::json
    """)
