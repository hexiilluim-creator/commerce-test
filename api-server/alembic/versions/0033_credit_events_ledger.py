"""0033 — credit_events ledger table (ledger immuable des crédits IA)

Revision ID: 0033_credit_events_ledger
Revises: 0032_customer_opted_out
Create Date: 2026-06-15 00:00:00

Pourquoi :
  credit_ledger.py tente de lire/écrire dans la table `credit_events` mais
  celle-ci n'existait pas encore (seul un commentaire TODO dans le code).
  Cette migration crée la table de ledger immuable des événements de crédits IA.

Structure :
  - id              BIGSERIAL PRIMARY KEY
  - store_id        FK -> stores (index pour les requêtes par tenant)
  - event_type      VARCHAR(32) : 'allocate', 'deduct', 'topup', 'expire', 'reset'
  - credits_delta   INTEGER     : variation (négatif pour déduction, positif pour ajout)
  - balance_after   INTEGER     : solde après l'événement (dénormalisé pour lecture rapide)
  - description     TEXT        : description lisible (ex: "GPT-4o: product search")
  - reference_id    VARCHAR(64) : ID externe (pack_id, interaction_id, etc.)
  - created_at      TIMESTAMPTZ : horodatage immuable (index BRIN)

Propriétés enterprise :
  - Immuable : pas de UPDATE/DELETE (audit trail)
  - Index BRIN sur created_at (append-only, très efficace)
  - Index B-tree sur (store_id, created_at DESC) pour les requêtes tenant
  - Pas de ON DELETE CASCADE intentionnel (données financières = conserver)
"""
import sqlalchemy as sa

from alembic import op

revision = "0033_credit_events_ledger"
down_revision = "0032_customer_opted_out"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table credit_events ───────────────────────────────────────────────────
    op.create_table(
        "credit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "store_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),  # RESTRICT intentionnel : pas de perte de données
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(32),
            nullable=False,
        ),  # CHECK constraint en dessous
        sa.Column("credits_delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── CHECK constraint sur event_type ───────────────────────────────────────
    op.create_check_constraint(
        "ck_credit_events_event_type",
        "credit_events",
        "event_type IN ('allocate', 'deduct', 'topup', 'expire', 'reset', 'refund')",
    )

    # ── CHECK constraint sur balance_after (jamais négatif) ──────────────────
    op.create_check_constraint(
        "ck_credit_events_balance_non_negative",
        "credit_events",
        "balance_after >= 0",
    )

    # ── Index B-tree : requêtes par tenant (le plus fréquent) ─────────────────
    op.create_index(
        "ix_credit_events_store_created",
        "credit_events",
        ["store_id", sa.text("created_at DESC")],
    )

    # ── Index BRIN : table append-only, très efficace pour les scans temporels ─
    # Note: BRIN n'est disponible qu'en PostgreSQL — ignoré silencieusement en SQLite
    try:
        op.execute(
            "CREATE INDEX ix_credit_events_created_brin "
            "ON credit_events USING BRIN (created_at)"
        )
    except Exception:
        # SQLite et autres dialectes : index B-tree standard comme fallback
        op.create_index(
            "ix_credit_events_created_brin",
            "credit_events",
            ["created_at"],
        )

    # ── Index sur reference_id (lookup par interaction_id, pack_id, etc.) ─────
    op.create_index(
        "ix_credit_events_reference_id",
        "credit_events",
        ["reference_id"],
        postgresql_where=sa.text("reference_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Suppression dans l'ordre inverse
    op.drop_index("ix_credit_events_reference_id", table_name="credit_events")
    try:
        op.drop_index("ix_credit_events_created_brin", table_name="credit_events")
    except Exception:
        pass
    op.drop_index("ix_credit_events_store_created", table_name="credit_events")
    op.drop_constraint("ck_credit_events_balance_non_negative", "credit_events", type_="check")
    op.drop_constraint("ck_credit_events_event_type", "credit_events", type_="check")
    op.drop_table("credit_events")
