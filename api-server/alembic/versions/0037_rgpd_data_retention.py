"""0037_rgpd_data_retention — RGPD: colonnes rétention + table gdpr_audit_log.

Ajoute:
  - stores.gdpr_deletion_requested_at  (Art. 17)
  - stores.gdpr_deletion_scheduled_at  (J+30)
  - customers.anonymized_at
  - table gdpr_audit_log               (Art. 5(2) accountability)

Revision ID: 0037_rgpd_data_retention
Revises: 0036_drift_fix_store_public_fields
"""
import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0037_rgpd_data_retention"
down_revision = "0036_drift_fix_store_public_fields"
branch_labels = None
depends_on = None


def _col(tbl, col):
    try:
        return col in [c["name"] for c in inspect(op.get_bind()).get_columns(tbl)]
    except Exception:
        return False


def _tbl(t):
    try:
        return t in inspect(op.get_bind()).get_table_names()
    except Exception:
        return False


def upgrade():
    if not _col("stores", "gdpr_deletion_requested_at"):
        op.add_column("stores", sa.Column(
            "gdpr_deletion_requested_at", sa.DateTime(timezone=True),
            nullable=True, comment="RGPD Art.17 — date demande d'effacement"))
    if not _col("stores", "gdpr_deletion_scheduled_at"):
        op.add_column("stores", sa.Column(
            "gdpr_deletion_scheduled_at", sa.DateTime(timezone=True),
            nullable=True, comment="Date purge effective = requested_at + 30j"))
    if not _col("customers", "anonymized_at"):
        op.add_column("customers", sa.Column(
            "anonymized_at", sa.DateTime(timezone=True),
            nullable=True, comment="Date anonymisation PII (RGPD Art.17)"))
    if not _tbl("gdpr_audit_log"):
        op.create_table("gdpr_audit_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("store_id", sa.Integer(),
                sa.ForeignKey("stores.id", ondelete="CASCADE"),
                nullable=False, index=True),
            sa.Column("action", sa.String(50), nullable=False,
                comment="export|delete_request|anonymize|purge"),
            sa.Column("performed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("ix_gdpr_audit_log_store",  "gdpr_audit_log", ["store_id"])
        op.create_index("ix_gdpr_audit_log_ts",     "gdpr_audit_log", ["created_at"])


def downgrade():
    if _tbl("gdpr_audit_log"):
        op.drop_index("ix_gdpr_audit_log_ts")
        op.drop_index("ix_gdpr_audit_log_store")
        op.drop_table("gdpr_audit_log")
    for col, tbl in [("gdpr_deletion_requested_at","stores"),
                     ("gdpr_deletion_scheduled_at","stores"),
                     ("anonymized_at","customers")]:
        if _col(tbl, col):
            op.drop_column(tbl, col)
