"""0034_enterprise_omnicall — Tables Enterprise Phase 1.

Révision : 0034_enterprise_omnicall
Tables créées :
  - conversation_memories   (mémoire long terme)
  - human_handoffs          (escalades humaines)
  - conversation_summaries  (résumés automatiques)
  - emotion_alerts          (log alertes émotionnelles)
Colonnes ajoutées :
  - customers.lead_score    (score 0-100)
  - customers.lead_label    (cold|warm|hot)
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0034_enterprise_omnicall"
down_revision = "0033_credit_events_ledger"  # FIX: was f2c7cdda776d (isolated stub not in main chain)
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── conversation_memories ──────────────────────────────────────────────────
    op.create_table(
        "conversation_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("source_channel", sa.String(30), nullable=True, server_default="whatsapp"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_conversation_memories_store_customer", "conversation_memories", ["store_id", "customer_id"])
    op.create_index("ix_conversation_memories_entry_type", "conversation_memories", ["entry_type"])

    # ── human_handoffs ─────────────────────────────────────────────────────────
    op.create_table(
        "human_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("original_message", sa.Text(), nullable=True),
        sa.Column("assigned_agent", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolution_time_minutes", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_human_handoffs_store_status", "human_handoffs", ["store_id", "status"])

    # ── conversation_summaries ─────────────────────────────────────────────────
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("main_objection", sa.Text(), nullable=True),
        sa.Column("next_actions", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(50), nullable=True),
        sa.Column("emotion", sa.String(30), nullable=True),
        sa.Column("emotion_score", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("lead_score", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("lead_label", sa.String(20), nullable=True, server_default="cold"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_conversation_summaries_store_customer", "conversation_summaries", ["store_id", "customer_id"])

    # ── emotion_alerts ─────────────────────────────────────────────────────────
    op.create_table(
        "emotion_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("emotion", sa.String(30), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("message_excerpt", sa.String(200), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── customers: colonnes lead_score / lead_label ────────────────────────────
    conn = op.get_bind()

    def _add_if_not_exists(table, col_name, col_type):
        exists = conn.execute(sa.text(
            f"SELECT 1 FROM information_schema.columns WHERE table_name='{table}' AND column_name='{col_name}'"
        )).fetchone()
        if not exists:
            conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))

    _add_if_not_exists("customers", "lead_score", "INTEGER DEFAULT 0")
    _add_if_not_exists("customers", "lead_label", "VARCHAR(20) DEFAULT 'cold'")
    _add_if_not_exists("customers", "created_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()")


def downgrade() -> None:
    op.drop_column("customers", "lead_label")
    op.drop_column("customers", "lead_score")
    op.drop_column("customers", "created_at")
    op.drop_table("emotion_alerts")
    op.drop_table("conversation_summaries")
    op.drop_table("human_handoffs")
    op.drop_table("conversation_memories")
