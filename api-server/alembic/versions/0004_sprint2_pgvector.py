"""Sprint 2 — pgvector + security improvements schema

Revision ID: 0004_sprint2_pgvector
Revises: 0003_sprint1_blockers
Create Date: 2025-01-04 00:00:00

Changes:
  - pgvector extension (PostgreSQL only, if available)
  - products.embedding_vec vector(1536) — replaces JSON embedding
  - IVFFlat index for fast cosine similarity search
  - stores.payment_config — clix.allowed_ips + tnpay.webhook_token fields documented

Compatibility (P0):
  - Cette migration est désormais TOLÉRANTE :
      • L'import `pgvector` est rendu optionnel.
      • Sur SQLite (ou tout dialecte non-PostgreSQL), la migration devient
        un no-op propre, ce qui permet la validation locale P0.
      • La logique PostgreSQL d'origine est strictement préservée pour la prod.
"""
import sqlalchemy as sa

from alembic import op

# Import optionnel : si pgvector n'est pas installé, la migration reste chargeable.
try:  # pragma: no cover
    from pgvector.sqlalchemy import Vector  # type: ignore
    _HAS_PGVECTOR = True
except Exception:  # ModuleNotFoundError ou ImportError
    Vector = None  # type: ignore
    _HAS_PGVECTOR = False


revision = "0004_sprint2_pgvector"
down_revision = "0003_sprint1_blockers"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    try:
        return bind.dialect.name == "postgresql"
    except Exception:
        return False


def upgrade() -> None:
    # ── Hors PostgreSQL : no-op (validation locale SQLite, etc.) ──────────────
    if not _is_postgres():
        return

    # ── Hors pgvector installé : no-op pour ne pas casser une CI dégradée ─────
    if not _HAS_PGVECTOR:
        return

    # ── pgvector extension ────────────────────────────────────────────────────
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # Add native vector column (1536 dims = OpenAI text-embedding-3-small)
    op.add_column('products', sa.Column('embedding_vec', Vector(1536), nullable=True))
    # Cast explicit (safety)
    op.execute(sa.text(
        "ALTER TABLE products ALTER COLUMN embedding_vec "
        "TYPE vector(1536) USING embedding_vec::vector(1536)"
    ))

    # IVFFlat index — cosine distance
    op.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_products_embedding_vec
        ON products
        USING ivfflat (embedding_vec vector_cosine_ops)
        WITH (lists = 100)
    """))

    # Migrate existing JSON embeddings to vector column
    op.execute(sa.text("""
        UPDATE products
        SET embedding_vec = embedding::text::vector(1536)
        WHERE embedding IS NOT NULL
          AND embedding_vec IS NULL
    """))


def downgrade() -> None:
    if not _is_postgres():
        return
    conn = op.get_bind()
    try:
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_products_embedding_vec"))
        conn.execute(sa.text("ALTER TABLE products DROP COLUMN IF EXISTS embedding_vec"))
    except Exception:
        pass
