"""0009_omnichannel_customer — Ajoute le canal de communication aux clients et logs

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-24

Objectif :
  - Customer : ajouter `channel` (whatsapp/instagram/facebook/tiktok) + `social_sender_id`
  - ConversationLog : ajouter `channel` pour tracer les transitions FSM par canal
  - Index sur (store_id, social_sender_id, channel) pour lookup rapide des clients sociaux
"""
import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Customer : canal + identifiant social ─────────────────────────────────
    op.add_column(
        "customers",
        sa.Column(
            "channel",
            sa.String(20),
            nullable=False,
            server_default="whatsapp",
            comment="Canal d'origine : whatsapp | instagram | facebook | tiktok",
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "social_sender_id",
            sa.String(128),
            nullable=True,
            comment="PSID Instagram/Facebook ou Open ID TikTok — null pour WhatsApp",
        ),
    )

    # Index composite pour lookup rapide au moment d'un message entrant social
    op.create_index(
        "ix_customers_store_channel_sender",
        "customers",
        ["store_id", "channel", "social_sender_id"],
    )

    # ── ConversationLog : canal ───────────────────────────────────────────────
    op.add_column(
        "conversation_logs",
        sa.Column(
            "channel",
            sa.String(20),
            nullable=False,
            server_default="whatsapp",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_logs", "channel")
    op.drop_index("ix_customers_store_channel_sender", table_name="customers")
    op.drop_column("customers", "social_sender_id")
    op.drop_column("customers", "channel")
