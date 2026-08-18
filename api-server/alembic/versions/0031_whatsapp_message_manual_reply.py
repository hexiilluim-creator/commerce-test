"""0031 — add direction + is_manual_reply to whatsapp_messages

Revision ID: 0031_whatsapp_message_manual_reply
Revises: 0030
Create Date: 2025-01-20 00:00:00

Raison :
  Le nouveau endpoint POST /conversations/{id}/reply permet au marchand
  d'envoyer une réponse manuelle pendant une prise de main (takeover).
  Ces réponses doivent être tracées dans whatsapp_messages avec :
    - direction='outbound' (vs 'inbound' pour les messages clients)
    - is_manual_reply=True (pour distinguer IA vs humain dans l'UI)

Compatibilité :
  - Base vide      : colonnes créées avec defaults -> OK
  - Base existante : ALTER TABLE ADD COLUMN avec server_default -> OK, pas de lock
  - Downgrade      : DROP COLUMN -> réversible (perte des logs de réponses manuelles)
"""
import sqlalchemy as sa

from alembic import op

revision = "0031_whatsapp_message_manual_reply"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_messages", sa.Column(
        "direction",
        sa.String(16),
        nullable=False,
        server_default=sa.text("'inbound'"),
        comment="inbound (client->IA) | outbound (IA/humain->client)",
    ))
    op.add_column("whatsapp_messages", sa.Column(
        "is_manual_reply",
        sa.Boolean(),
        nullable=False,
        server_default=sa.text("false"),
        comment="True quand le marchand a répondu manuellement (prise de main)",
    ))
    # Index pour retrouver rapidement les réponses manuelles par store
    op.create_index(
        "ix_whatsapp_messages_store_manual",
        "whatsapp_messages",
        ["store_id", "is_manual_reply"],
        postgresql_where=sa.text("is_manual_reply = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_messages_store_manual", table_name="whatsapp_messages")
    op.drop_column("whatsapp_messages", "is_manual_reply")
    op.drop_column("whatsapp_messages", "direction")
